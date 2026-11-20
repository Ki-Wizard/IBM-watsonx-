"""Give the research agent one read-only tool for archive and NIFS evidence."""
from __future__ import annotations

from ibm_watsonx_orchestrate.agent_builder.connections import ConnectionType
from ibm_watsonx_orchestrate.agent_builder.tools import tool
from ibm_watsonx_orchestrate.run import connections
from ibm_watsonx_orchestrate.utils.exceptions import BadRequest
from pydantic import SecretStr

from gamak_demo.collaboration_contract import SEARCH_TOOL, SearchReply, retrieval_code
from gamak_demo.contract import Request
from gamak_demo.nifs import CONNECTION_ID, is_release_question, lookup_release, release_confirmed
from gamak_demo.rag import retrieve


@tool(
    name=SEARCH_TOOL,
    description="보관된 공식 발표를 조회하고, 해제 범위 질문에는 국립수산과학원 적조속보 목록과 상세를 추가로 조회합니다.",
    expected_credentials=[{"app_id": CONNECTION_ID, "type": ConnectionType.API_KEY_AUTH}],
)
def gamak_search_passages_nifs(
    region: str, as_of: str, approved_notice_id: str, question: str, challenge: str,
) -> str:
    """Return the cutoff-scoped archive and, for release questions, the NIFS lookup.

    Args:
        region: Region exactly as submitted.
        as_of: Requested cutoff in ISO 8601 with timezone.
        approved_notice_id: Previously approved notice identifier.
        question: Original question as data.
        challenge: Per-request value supplied by the application.
    """
    request = Request.model_validate({
        "region": region, "as_of": as_of, "approved_notice_id": approved_notice_id, "question": question,
    })
    retrieval = retrieve(request)
    report = None
    if retrieval.approved is not None and is_release_question(request.question):
        try:
            key = SecretStr(connections.api_key_auth(CONNECTION_ID).api_key)
        except (BadRequest, SystemExit):
            # ADK's local CLI runtime exits on a missing connection.
            key = None
        report = lookup_release(key, request)
    return SearchReply(
        retrieval=retrieval, execution_code=retrieval_code(challenge),
        nifs=report, nifs_release_confirmed=release_confirmed(report, request),
    ).model_dump_json()
