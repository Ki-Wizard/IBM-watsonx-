"""Reject a proposal whose citations do not support the two separate alerts."""
import json
from pathlib import Path
from uuid import uuid4

import pytest
from pytest import MonkeyPatch

from gamak_demo import collaborative
from gamak_demo.collaboration_contract import (
    SEARCH_TOOL,
    ReviewProposal,
    SearchReply,
    retrieval_code,
)
from gamak_demo.collaborative import HANDOFF, verified_citations, verify_run
from gamak_demo.contract import Request
from gamak_demo.rag import retrieve
from gamak_demo.service import prepare
from gamak_demo.watsonx import (
    AgentRun,
    Chat,
    Choice,
    History,
    Message,
    Settings,
    Step,
    StepGroup,
    WatsonxProblem,
)

FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "gamak-update.request.json"


def test_proposal_must_cite_each_alert_using_the_right_passage() -> None:
    request = Request.model_validate_json(FIXTURE.read_bytes())
    assessment = prepare(request).assessment
    passages = retrieve(request).passages
    proposal = ReviewProposal.model_validate({
        "decision": "갱신 필요",
        "regional_citation": "mof-62990-regional",
        "government_citation": "mof-62990-government",
    })
    citations = verified_citations(proposal, passages, assessment)
    assert [item.topic for item in citations] == ["regional", "government"]

    with pytest.raises(WatsonxProblem):
        verified_citations(proposal.model_copy(update={"regional_citation": "mof-62990-government"}),
                           passages, assessment)
    with pytest.raises(WatsonxProblem):
        verified_citations(proposal.model_copy(update={"regional_citation": "mof-63302-regional"}),
                           passages, assessment)
    with pytest.raises(WatsonxProblem):
        verified_citations(proposal.model_copy(update={"decision": "유지"}), passages, assessment)


def recorded_run(
    search: SearchReply, *, handoff_content: str = "Transferring", search_first: bool = False,
) -> AgentRun:
    content = ('{"decision":"갱신 필요","regional_citation":"mof-62990-regional",'
               '"government_citation":"mof-62990-government"}')
    chat = Chat(thread_id=uuid4(), choices=(Choice(message=Message(content=content)),))
    handoff_steps = (
        Step(type="tool_response", name=HANDOFF, tool_call_id="handoff", content=handoff_content),
        Step(type="tool_call", name=HANDOFF, tool_call_id="handoff"),
    )
    search_steps = (
        Step(type="tool_response", name=SEARCH_TOOL, tool_call_id="search", content=search.model_dump_json()),
        Step(type="tool_call", name=SEARCH_TOOL, tool_call_id="search"),
    )
    steps = (*search_steps, *handoff_steps) if search_first else (*handoff_steps, *search_steps)
    history = History(role="assistant", step_history=(StepGroup(step_details=steps),))
    return AgentRun(chat, (history,))


def test_verified_run_requires_matching_handoff_search_and_receipt() -> None:
    request = Request.model_validate_json(FIXTURE.read_bytes())
    assessment = prepare(request).assessment
    search = SearchReply(retrieval=retrieve(request), execution_code=retrieval_code("nonce"))
    run = recorded_run(search)
    assert len(verify_run(run, search, assessment).citations) == 2

    with pytest.raises(WatsonxProblem):
        verify_run(AgentRun(run.chat, ()), search, assessment)
    with pytest.raises(WatsonxProblem):
        wrong = search.model_copy(update={"execution_code": retrieval_code("old-nonce")})
        verify_run(run, wrong, assessment)


@pytest.mark.parametrize("failed_handoff", ["error-reply", "search-before-handoff"])
def test_verified_run_rejects_a_failed_or_late_handoff(failed_handoff: str) -> None:
    request = Request.model_validate_json(FIXTURE.read_bytes())
    assessment = prepare(request).assessment
    search = SearchReply(retrieval=retrieve(request), execution_code=retrieval_code("nonce"))
    invalid = (
        recorded_run(search, handoff_content="ERROR: collaborator unavailable")
        if failed_handoff == "error-reply" else recorded_run(search, search_first=True)
    )
    with pytest.raises(WatsonxProblem):
        verify_run(invalid, search, assessment)


def test_collaboration_retries_before_storing_when_first_trace_is_invalid(
    tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    request = Request.model_validate_json(FIXTURE.read_bytes())
    db = tmp_path / "retry.sqlite3"
    challenges: list[str] = []
    monkeypatch.setenv("WXO_ENDPOINT_URL", "https://api.us-south.watson-orchestrate.cloud.ibm.com/instances/test")
    monkeypatch.setenv("WXO_API_KEY", "test-token")

    def run_again(request_text: str, settings: Settings) -> AgentRun:
        assert settings.agent_name == collaborative.SUPERVISOR
        assert not db.exists()
        challenge = str(json.loads(request_text)["challenge"])
        challenges.append(challenge)
        run = recorded_run(SearchReply(retrieval=retrieve(request), execution_code=retrieval_code(challenge)))
        return AgentRun(run.chat, ()) if len(challenges) == 1 else run

    monkeypatch.setattr(collaborative, "run_agent", run_again)
    outcome = collaborative.review_collaborative(request, db)

    assert len(set(challenges)) == 2
    assert outcome.result.ledger.before == 0 and outcome.result.ledger.after == 1

    repeated = collaborative.review_collaborative(request, db, previous=outcome)
    assert repeated.reused and len(challenges) == 2
    assert repeated.collaboration == outcome.collaboration
    assert repeated.result.ledger.before == repeated.result.ledger.after == 1
    assert repeated.result.draft == outcome.result.draft
