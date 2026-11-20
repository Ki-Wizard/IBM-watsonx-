from datetime import datetime

import httpx2
import pytest
from pydantic import SecretStr

from gamak_demo.contract import KST, NoticeId, Request
from gamak_demo.nifs import NifsReport, NifsUnavailable, fetch_release
from gamak_demo.service import prepare

CODE = "20250925-001"
BREAKING = "- 특보 해제 : 사천·강진만, 가막만\n- 예비특보로 하향 : 전남 득량만"


def release_request(day: int = 26, hour: int = 10) -> Request:
    return Request(
        region="가막만", as_of=datetime(2025, 9, day, hour, 30, tzinfo=KST),
        approved_notice_id=NoticeId("gamak-2025-08-29-demo"), question="가막만도 특보 해제 대상인가요?",
    )


def api_response(body: dict[str, list[dict[str, str]]]) -> httpx2.Response:
    return httpx2.Response(200, json={"header": {"resultCode": "00"}, "body": body})


def search_breaking(request: Request, breaking: str, *, code: str = CODE) -> NifsReport:
    calls: list[str] = []

    def reply(call: httpx2.Request) -> httpx2.Response:
        operation = call.url.params["id"]
        calls.append(operation)
        assert call.url.host == "www.nifs.go.kr"
        assert call.url.params["key"] == "fixture-license"
        if operation == "redtideList":
            assert call.url.params["edate"] == f"{request.as_of:%Y%m%d}"
            return api_response({"items": [{"cod_news": code, "day_report": "2025-09-25"}]})
        assert call.url.params["cod_news"] == code
        return api_response({"item": [{"cod_news": code, "day_report": "2025-09-25", "txt_breaking": breaking}]})

    with httpx2.Client(transport=httpx2.MockTransport(reply)) as client:
        result = fetch_release(client, SecretStr("fixture-license"), request)
    assert calls == ["redtideList", "redtideDetail"]
    return result


def test_verified_release_uses_nifs_region_and_mof_government() -> None:
    request = release_request()
    report = search_breaking(request, BREAKING)

    outcome = prepare(request, nifs=report)

    assert outcome.assessment.decision == "갱신 필요"
    regional, government = outcome.assessment.regional_alert, outcome.assessment.government_alert
    assert regional is not None and regional.current == "해제" and regional.effective_at is None
    assert regional.evidence_id == "nifs-20250925-001"
    assert government is not None and government.current == "주의" and government.evidence_id == "mof-63302"


def test_live_detail_accepts_adjacent_downgrade_heading() -> None:
    request = release_request()
    breaking = "- 특보 해제 : 사천·강진만, 가막만- 예비특보로 하향 : 경남 중부 앞바다, 전남 득량만\r\r\n"

    outcome = prepare(request, nifs=search_breaking(request, breaking))

    assert outcome.assessment.decision == "갱신 필요"
    source = next(item for item in outcome.assessment.evidence if item.publisher == "국립수산과학원")
    assert "가막만" in source.summary and "득량만" not in source.summary


@pytest.mark.parametrize(
    ("day", "code", "breaking"),
    [
        (25, CODE, BREAKING),
        (26, "20250925-999", BREAKING),
        (26, CODE, "- 특보 해제 : 사천·강진만\n- 가막만 예비특보 유지"),
        (26, CODE, "- 특보 해제 검토 : 가막만"),
    ],
)
def test_ambiguous_scope_or_availability_does_not_create_draft(day: int, code: str, breaking: str) -> None:
    request = release_request(day, 17)

    outcome = prepare(request, nifs=search_breaking(request, breaking, code=code))

    assert outcome.assessment.decision == "확인 필요"
    assert outcome.assessment.follow_up_question and outcome.draft is None
    assert all(source.publisher == "해양수산부" for source in outcome.assessment.evidence)


def test_license_error_uses_archive_fallback() -> None:
    request = release_request()

    def denied(call: httpx2.Request) -> httpx2.Response:
        assert call.url.params["id"] == "redtideList"
        return httpx2.Response(200, json={"header": {"resultCode": "02", "resultMsg": "invalid license"}, "body": {}})

    with httpx2.Client(transport=httpx2.MockTransport(denied)) as client:
        report = fetch_release(client, SecretStr("fixture-license"), request)

    assert report == NifsUnavailable(reason="license")
    assert prepare(request, nifs=report) == prepare(request)


def test_direct_release_question_before_release_requires_confirmation() -> None:
    request = release_request().model_copy(update={"as_of": datetime(2025, 8, 30, 10, tzinfo=KST)})

    assert prepare(request).assessment.decision == "확인 필요"


def test_api_query_key_is_omitted_from_http_logs(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO", logger="httpx2"):
        search_breaking(release_request(), BREAKING)

    assert "fixture-license" not in caplog.text
