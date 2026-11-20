"""Pack this tool and the public replay archive for watsonx Orchestrate."""
from __future__ import annotations

from ibm_watsonx_orchestrate.agent_builder.tools import tool

from gamak_demo.agent_contract import TOOL_NAME, AgentReply, execution_code
from gamak_demo.contract import Request
from gamak_demo.service import prepare


@tool(
    name=TOOL_NAME,
    description="기준시각까지 확인 가능한 해양수산부 적조 발표와 가상 승인본을 대조합니다.",
)
def gamak_official_evidence(request_json: str, challenge: str) -> str:
    """Return the official evidence assessment from the replay archive.

    Args:
        request_json: UTF-8 JSON with region, as_of, approved_notice_id and question.
        challenge: Per-request value supplied by the demo backend.
    """
    request = Request.model_validate_json(request_json)
    return AgentReply(
        assessment=prepare(request).assessment,
        execution_code=execution_code(challenge),
    ).model_dump_json()
