"""Exercise fixture lookup, adjudication and real SQLite writes."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Final

import pytest

from gamak_demo.contract import Request
from gamak_demo.service import review

ROOT: Final = Path(__file__).resolve().parents[1]
EXAMPLES: Final = ROOT / "examples"
REQUEST: Final = Request.model_validate_json(
    (EXAMPLES / "gamak-update.request.json").read_text(encoding="utf-8"),
)


def test_update_then_reuse_draft(tmp_path: Path) -> None:
    db = tmp_path / "demo.sqlite3"
    first = review(REQUEST, db)
    second = review(REQUEST, db)

    expected = json.loads((EXAMPLES / "gamak-update.expected.json").read_text(encoding="utf-8"))
    assert first.model_dump(mode="json") == expected
    assert first.draft is not None and second.draft == first.draft
    assert (second.ledger.before, second.ledger.after, second.ledger.action) == (1, 1, "reused")
    with closing(sqlite3.connect(db)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM drafts").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM checks").fetchone() == (2,)


def test_keep_with_only_sources_known_at_cutoff(tmp_path: Path) -> None:
    request = REQUEST.model_copy(
        update={"as_of": datetime.fromisoformat("2025-08-26T16:30:00+09:00")},
    )
    result = review(request, tmp_path / "demo.sqlite3")
    assert result.decision == "유지"
    assert [source.id for source in result.evidence] == ["mof-62891"]
    assert result.draft is None and result.ledger.after == 0


def test_unclear_region_asks_for_scope(tmp_path: Path) -> None:
    request = REQUEST.model_copy(update={"region": "일부 해역"})
    result = review(request, tmp_path / "demo.sqlite3")
    assert result.decision == "확인 필요"
    assert result.follow_up_question and "해역" in result.follow_up_question
    assert result.ledger.after == 0 and result.draft is None


def test_missing_temperature_keeps_verified_change(tmp_path: Path) -> None:
    result = review(REQUEST, tmp_path / "demo.sqlite3")
    assert result.decision == "갱신 필요"
    assert result.water_temperature.celsius is None
    assert result.water_temperature.status == "확인 필요"
    assert result.draft is not None and "수온" in result.draft.text


@pytest.mark.parametrize("broken", [False, True])
def test_source_failure_leaves_confirmation_in_check_history(
    tmp_path: Path, *, broken: bool,
) -> None:
    archive = tmp_path / "official.json"
    if broken:
        archive.write_text('{"documents": []}', encoding="utf-8")
    db = tmp_path / "demo.sqlite3"
    result = review(REQUEST, db, archive=archive)

    assert result.decision == "확인 필요"
    assert result.ledger.after == 0 and result.draft is None
    with closing(sqlite3.connect(db)) as connection:
        assert connection.execute("SELECT decision FROM checks").fetchone() == ("확인 필요",)
