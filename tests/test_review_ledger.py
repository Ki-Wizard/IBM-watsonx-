import sqlite3
from contextlib import closing
from pathlib import Path

from gamak_demo import ledger
from gamak_demo.contract import Request
from gamak_demo.demo import EXAMPLES
from gamak_demo.service import review


def test_legacy_inbox_can_be_opened_read_only(tmp_path: Path) -> None:
    db = tmp_path / "legacy.sqlite3"
    request = Request.model_validate_json((EXAMPLES / "gamak-update.request.json").read_bytes())
    created = review(request, db)
    with closing(sqlite3.connect(db)) as connection, connection:
        connection.execute("DROP TABLE IF EXISTS check_notes")
        connection.execute("DROP TABLE IF EXISTS draft_dispositions")
    before = db.read_bytes()

    inbox = ledger.read_ledger(db)

    assert [item.result for item in inbox.drafts] == [created]
    assert inbox.drafts[0].disposition is None
    assert db.read_bytes() == before


def test_confirmation_note_is_saved_without_changing_official_decision(tmp_path: Path) -> None:
    db = tmp_path / "scope.sqlite3"
    request = Request.model_validate_json((EXAMPLES / "test-cases/case4-unknown-region.request.json").read_bytes())
    initial = review(request, db)
    note = ledger.ReviewNote(reviewer="당직자", note="가막만 해제를 들었음")

    retried = review(request, db, note=note)

    assert retried == initial
    snapshot = ledger.read_ledger(db)
    assert not snapshot.drafts
    assert snapshot.checks[0].note == note
    assert retried.follow_up_question


def test_final_status_survives_reload_and_reuse(tmp_path: Path) -> None:
    db = tmp_path / "inbox.sqlite3"
    request = Request.model_validate_json((EXAMPLES / "gamak-update.request.json").read_bytes())
    first = review(request, db)
    assert first.draft is not None
    approved = ledger.Disposition(status="승인", reviewer="당직자", note="공식 발표 대조")
    rejected = ledger.Disposition(status="반려", reviewer="다른 당직자", note="처리 충돌")

    assert ledger.set_disposition(db, first.draft.id, approved)
    assert not ledger.set_disposition(db, first.draft.id, rejected)
    repeat = review(request, db)

    inbox = ledger.read_ledger(db)
    assert len(inbox.drafts) == 1
    assert inbox.drafts[0].disposition is not None
    assert inbox.drafts[0].disposition.action == approved
    assert inbox.drafts[0].disposition.at.tzinfo is not None
    assert repeat.ledger.action == "reused"
    assert inbox.checks[0].result.draft == first.draft
