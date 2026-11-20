"""Validate the live researcher handoff before committing to the shared inbox."""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from secrets import token_hex
from typing import Final
from uuid import UUID

from pydantic import ValidationError

from .collaboration_contract import (
    RESEARCHER,
    SEARCH_TOOL,
    SUPERVISOR,
    ReviewProposal,
    SearchReply,
    retrieval_code,
)
from .contract import Assessment, Request, Result
from .rag import Passage, PassageId, Retrieval, retrieve
from .service import finalize, prepare
from .watsonx import AgentRun, Settings, Step, WatsonxProblem, proposal_json, run_agent

HANDOFF: Final = f"chat_with_collaborator_{RESEARCHER}"


class UnverifiedRun(WatsonxProblem):
    """IBM replied, but its handoff, retrieval, or proposal could not be verified."""


@dataclass(frozen=True, slots=True)
class Collaboration:
    thread_id: UUID
    trace_id: str | None
    citations: tuple[Passage, ...]


@dataclass(frozen=True, slots=True)
class CollaborativeReview:
    result: Result
    collaboration: Collaboration
    request: Request
    assessment: Assessment
    retrieval: Retrieval
    reused: bool = False


def _response(steps: tuple[Step, ...], name: str) -> tuple[int, str]:
    calls = tuple((index, step) for index, step in enumerate(steps) if step.type == "tool_call" and step.name == name)
    replies = tuple(step for step in steps if step.type == "tool_response" and step.name == name)
    if len(calls) == len(replies) == 1:
        index, call = calls[0]
        reply = replies[0]
        if call.tool_call_id and call.tool_call_id == reply.tool_call_id and reply.content:
            return index, reply.content
    message = "IBM 이력에서 근거 조사 에이전트의 인계와 검색 실행을 확인하지 못했습니다."
    raise UnverifiedRun(message)


def verified_citations(
    proposal: ReviewProposal, passages: tuple[Passage, ...], assessment: Assessment,
) -> tuple[Passage, ...]:
    indexed = {item.id: item for item in passages}
    expected = tuple(
        PassageId(f"{alert.evidence_id}-{topic}") if alert else None
        for alert, topic in ((assessment.regional_alert, "regional"), (assessment.government_alert, "government"))
    )
    proposed = (proposal.regional_citation, proposal.government_citation)
    if (
        proposal.decision != assessment.decision or proposed != expected
        or any(item is not None and item not in indexed for item in proposed)
    ):
        message = "IBM이 제안한 판정 또는 인용이 기준시각의 공식 근거와 일치하지 않습니다."
        raise UnverifiedRun(message)
    return tuple(indexed[item] for item in proposed if item is not None)


def verify_run(run: AgentRun, expected: SearchReply, assessment: Assessment) -> Collaboration:
    steps = tuple(
        step
        for message in run.history if message.role == "assistant"
        for group in message.step_history or ()
        for step in group.step_details
    )
    handoff_index, handoff_reply = _response(steps, HANDOFF)
    search_index, search_reply = _response(steps, SEARCH_TOOL)
    # History can list the response before its call. Compare call positions only.
    if handoff_index >= search_index or not handoff_reply.strip().casefold().startswith("transferring"):
        message = "IBM 이력에서 공식 근거 검색에 앞선 조사 위임을 확인하지 못했습니다."
        raise UnverifiedRun(message)
    try:
        actual = SearchReply.model_validate_json(search_reply)
        proposal = ReviewProposal.model_validate_json(proposal_json(run.chat))
    except ValidationError:
        message = "IBM 협업 응답이 판정과 인용을 검증할 수 있는 형식이 아닙니다."
        raise UnverifiedRun(message) from None
    if actual != expected:
        message = "IBM 검색 이력의 공식 원문 또는 실행 검증 코드가 일치하지 않습니다."
        raise UnverifiedRun(message)
    return Collaboration(
        run.chat.thread_id, run.chat.trace_id,
        verified_citations(proposal, actual.retrieval.passages, assessment),
    )


def _verified_attempt(
    request: Request, settings: Settings, retrieval: Retrieval, assessment: Assessment,
) -> Collaboration:
    challenge = token_hex(8)
    request_text = json.dumps({**request.model_dump(mode="json"), "challenge": challenge}, ensure_ascii=False)
    run = run_agent(request_text, settings)
    expected = SearchReply(retrieval=retrieval, execution_code=retrieval_code(challenge))
    return verify_run(run, expected, assessment)


def review_collaborative(
    request: Request, db: Path, *, previous: CollaborativeReview | None = None,
) -> CollaborativeReview:
    """Ask the supervisor for a decision grounded in an observed collaborator search."""
    prepared = prepare(request)
    retrieval = retrieve(request)
    if (
        previous is not None and request == previous.request
        and prepared.assessment == previous.assessment and retrieval == previous.retrieval
    ):
        return replace(previous, result=finalize(prepared, db, "watsonx"), reused=True)

    settings = replace(Settings.from_env(), agent_name=SUPERVISOR)
    try:
        trace = _verified_attempt(request, settings, retrieval, prepared.assessment)
    except UnverifiedRun:
        trace = _verified_attempt(request, settings, retrieval, prepared.assessment)
    return CollaborativeReview(finalize(prepared, db, "watsonx"), trace, request, prepared.assessment, retrieval)
