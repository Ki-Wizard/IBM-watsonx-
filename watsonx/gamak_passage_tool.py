"""Expose public, date-scoped excerpts to the evidence research agent."""
from __future__ import annotations

from ibm_watsonx_orchestrate.agent_builder.tools import tool

from gamak_demo.collaboration_contract import SEARCH_TOOL, SearchReply, retrieval_code
from gamak_demo.contract import Request
from gamak_demo.rag import retrieve


@tool(name=SEARCH_TOOL, description="가막만 공식 보도자료에서 기준시각에 확인 가능한 원문 발췌와 직전 승인본을 조회합니다.")
def gamak_search_passages(
    region: str, as_of: str, approved_notice_id: str, question: str, challenge: str,
) -> str:
    """Return released excerpts and the approved baseline without a final assessment.

    Args:
        region: Region exactly as submitted.
        as_of: Requested cutoff in ISO 8601 with timezone.
        approved_notice_id: Previously approved notice identifier.
        question: The duty officer's question, kept in its original language.
        challenge: Per-request value supplied by the application.
    """
    request = Request.model_validate({
        "region": region, "as_of": as_of, "approved_notice_id": approved_notice_id,
        "question": question,
    })
    return SearchReply(
        retrieval=retrieve(request), execution_code=retrieval_code(challenge),
    ).model_dump_json()
