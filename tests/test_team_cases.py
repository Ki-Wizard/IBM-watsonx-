"""Verify the five cases from the team's prompt branch against the local contract."""
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict

from gamak_demo.contract import Decision, EvidenceId, Request, Result
from gamak_demo.service import review

CASES: Final = Path(__file__).resolve().parents[1] / "examples" / "test-cases"


class Scenario(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: int
    expected_decision: Decision
    primary_evidence_id: EvidenceId
    request: Request
    expected: Result


class ScenarioCollection(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenarios: tuple[Scenario, ...]


def test_team_scenarios_match_shared_contract(tmp_path: Path) -> None:
    shared = tmp_path / "update-repeat-and-scope.sqlite3"
    names = (
        "case1-update", "case2-maintain", "case3-repeat",
        "case4-unknown-region", "case5-missing-temp",
    )
    collection = ScenarioCollection.model_validate_json((CASES.parent / "demo-scenarios.json").read_bytes())
    for case_id, (name, scenario) in enumerate(zip(names, collection.scenarios, strict=True), start=1):
        request = Request.model_validate_json((CASES / f"{name}.request.json").read_bytes())
        expected = Result.model_validate_json((CASES / f"{name}.expected.json").read_bytes())
        assert scenario.case_id == case_id
        assert scenario.request == request, name
        assert scenario.expected == expected, name
        assert scenario.expected_decision == expected.decision, name
        assert scenario.primary_evidence_id in {evidence.id for evidence in expected.evidence}, name
        db = shared if name.startswith(("case1", "case3", "case4")) else tmp_path / f"{name}.sqlite3"
        assert review(request, db) == expected, name
