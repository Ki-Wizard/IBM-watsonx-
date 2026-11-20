"""Retrieval uses the request's historical cutoff and keeps evidence types distinct."""
from datetime import datetime
from pathlib import Path

from gamak_demo.contract import KST, NoticeId, Request
from gamak_demo.rag import retrieve
from gamak_demo.service import review


def request_at(month: int, day: int, question: str) -> Request:
    return Request(
        region="가막만", as_of=datetime(2025, month, day, 16, 30, tzinfo=KST),
        approved_notice_id=NoticeId("gamak-2025-08-29-demo"), question=question,
    )


def test_same_release_question_only_retrieves_sources_known_at_cutoff(tmp_path: Path) -> None:
    question = "남해안 일부 해역 특보가 해제되었다는데 가막만 안내를 종료해도 되나요?"
    early = request_at(8, 29, question)
    late = request_at(9, 25, question)

    assert all(passage.source_id != "mof-63302" for passage in retrieve(early).passages)
    just_before = late.model_copy(update={"as_of": late.as_of.replace(hour=15, minute=59)})
    assert all(passage.source_id != "mof-63302" for passage in retrieve(just_before).passages)
    at_cutoff = late.model_copy(update={"as_of": late.as_of.replace(minute=0)})
    assert any(passage.source_id == "mof-63302" for passage in retrieve(at_cutoff).passages)
    assert any(
        passage.source_id == "mof-63302" and passage.topic == "regional" and "가막만" in passage.text
        for passage in retrieve(late).passages
    )
    db = tmp_path / "releases.sqlite3"
    before, after = review(early, db), review(late, db)
    assert before.decision == "확인 필요" and before.ledger.after == 0
    assert after.decision == "갱신 필요" and after.ledger.after == 1
    assert after.regional_alert is not None and after.regional_alert.current == "해제"
    assert after.regional_alert.effective_at is None
    assert after.government_alert is not None and after.government_alert.current == "주의"
    assert after.government_alert.effective_at == datetime(2025, 9, 25, 16, tzinfo=KST)


def test_temperature_background_is_retrieved_without_becoming_a_measurement(tmp_path: Path) -> None:
    request = request_at(8, 29, "가막만 실측 수온은 24~27도인가요?")
    bundle = retrieve(request)
    assert any(passage.topic == "water_background" and "24~27℃" in passage.text for passage in bundle.passages)
    assert review(request, tmp_path / "temperature.sqlite3").water_temperature.celsius is None


def test_notice_end_question_waits_for_gamak_release_evidence(tmp_path: Path) -> None:
    question = "가막만 안내를 종료해도 되나요?"
    early = request_at(8, 29, question).model_copy(
        update={"approved_notice_id": NoticeId("gamak-2025-08-26-demo")},
    )
    db = tmp_path / "notice-end.sqlite3"

    before = review(early, db)
    after = review(request_at(9, 25, question), db)

    assert before.decision == "확인 필요"
    assert before.draft is None and before.ledger.after == 0
    assert after.decision == "갱신 필요"
    assert after.regional_alert is not None and after.regional_alert.current == "해제"
    assert after.draft is not None and after.ledger.after == 1


def test_latest_excerpts_do_not_repeat_older_alerts_from_the_approval() -> None:
    query = request_at(8, 29, "이 안내를 계속 써도 되나?").model_copy(
        update={"approved_notice_id": NoticeId("gamak-2025-08-26-demo")},
    )
    bundle = retrieve(query)
    assert bundle.approved is not None and bundle.approved.regional == "예비특보"
    assert [(item.id, item.level) for item in bundle.passages] == [
        ("mof-62990-regional", "적조주의보"), ("mof-62990-government", "경계"),
    ]
