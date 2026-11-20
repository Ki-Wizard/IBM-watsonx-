"""Run the five scenarios from the team's two-agent handoff against the ledger."""
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime

from gamak_demo.collaboration_contract import ReviewProposal
from gamak_demo.collaborative import verified_citations
from gamak_demo.contract import (
    Contract,
    Draft,
    GovernmentLevel,
    LedgerStatus,
    RegionLevel,
    Request,
)
from gamak_demo.rag import ApprovedLevels, PassageId, retrieve
from gamak_demo.service import prepare, review


class ExpectedPassage(Contract):
    id: PassageId
    level: RegionLevel | GovernmentLevel
    effective_at: AwareDatetime | None
    text: str


class ExpectedHandoff(Contract):
    scope_status: Literal["confirmed", "ambiguous", "not_found"]
    approved: ApprovedLevels
    regional: ExpectedPassage
    government: ExpectedPassage


class ExpectedResult(Contract):
    draft_text: str | None
    follow_up_question: str | None
    ledger: LedgerStatus


class Scenario(Contract):
    scenario_id: str
    category: str
    description: str
    request: Request
    agent1_handoff: ExpectedHandoff
    agent2_output: ReviewProposal
    backend_finalized: ExpectedResult


class Scenarios(Contract):
    title: str
    version: str
    scenarios: tuple[Scenario, ...]


def test_shared_cutoffs_ambiguity_and_inbox_match_pr_scenarios(tmp_path: Path) -> None:
    fixture = Path(__file__).resolve().parents[1] / "examples" / "two-agent-scenarios.json"
    cases = Scenarios.model_validate_json(fixture.read_bytes()).scenarios
    shared = tmp_path / "team.sqlite3"
    assert len(cases) == 5
    assert cases[0].request.model_copy(update={"as_of": cases[1].request.as_of}) == cases[1].request
    assert cases[1].request == cases[2].request
    first_draft: Draft | None = None

    for case in cases:
        db = tmp_path / "water.sqlite3" if case.scenario_id == "missing-water-temperature" else shared
        handoff = case.agent1_handoff
        retrieval = retrieve(case.request)
        assert retrieval.approved == handoff.approved
        assessment = prepare(case.request).assessment
        citations = verified_citations(case.agent2_output, retrieval.passages, assessment)
        assert len(citations) == 2
        for actual, expected_passage in zip(citations, (handoff.regional, handoff.government), strict=True):
            assert actual.id == expected_passage.id
            assert actual.level == expected_passage.level
            assert actual.effective_at == expected_passage.effective_at
            assert actual.text == expected_passage.text
            assert actual.published_at <= case.request.as_of

        result = review(case.request, db)
        expected = case.backend_finalized
        assert result.decision == case.agent2_output.decision, case.scenario_id
        assert (result.draft.text if result.draft else None) == expected.draft_text, case.scenario_id
        assert result.follow_up_question == expected.follow_up_question, case.scenario_id
        assert (handoff.scope_status == "ambiguous") == bool(expected.follow_up_question), case.scenario_id
        assert result.ledger == expected.ledger, case.scenario_id
        if case.scenario_id == "cutoff-compare-update":
            first_draft = result.draft
        if case.scenario_id == "repeat-idempotency":
            assert first_draft is not None and result.draft == first_draft
        if case.scenario_id == "missing-water-temperature":
            assert result.water_temperature.status == "확인 필요"
