"""Verify the five cases from the team's prompt branch against the local contract."""
from pathlib import Path
from typing import Final

from gamak_demo.contract import Request, Result
from gamak_demo.service import review

CASES: Final = Path(__file__).resolve().parents[1] / "examples" / "test-cases"


def test_team_scenarios_match_shared_contract(tmp_path: Path) -> None:
    shared = tmp_path / "update-repeat-and-scope.sqlite3"
    for name in (
        "case1-update", "case2-maintain", "case3-repeat",
        "case4-unknown-region", "case5-missing-temp",
    ):
        request = Request.model_validate_json((CASES / f"{name}.request.json").read_bytes())
        expected = Result.model_validate_json((CASES / f"{name}.expected.json").read_bytes())
        db = shared if name.startswith(("case1", "case3", "case4")) else tmp_path / f"{name}.sqlite3"
        assert review(request, db) == expected, name
