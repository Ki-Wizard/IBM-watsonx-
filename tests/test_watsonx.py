"""Check the JSON and tool confirmation required before IBM storage."""
from pathlib import Path
from uuid import uuid4

import pytest

from gamak_demo.agent_contract import TOOL_NAME, AgentReply, execution_code
from gamak_demo.contract import Request
from gamak_demo.service import prepare
from gamak_demo.watsonx import (
    Chat,
    Choice,
    History,
    Message,
    Step,
    StepGroup,
    WatsonxProblem,
    _verified_reply,
)

BASE = Path(__file__).resolve().parents[1]
REQUEST = Request.model_validate_json(
    (BASE / "examples/gamak-update.request.json").read_text(encoding="utf-8"),
)


def test_watsonx_requires_result_from_named_tool() -> None:
    expected = AgentReply(assessment=prepare(REQUEST).assessment, execution_code=execution_code("challenge"))
    content = expected.model_dump_json()
    proposal = '{"decision":"갱신 필요","evidence_ids":["mof-62891","mof-62990"]}'
    chat = Chat(thread_id=uuid4(), choices=(Choice(message=Message(content=proposal)),))
    record = History(role="assistant", step_history=(StepGroup(step_details=(
        Step(type="tool_response", name=TOOL_NAME, content=content),
    )),))

    assert _verified_reply(chat, (record,), expected) == expected
    with pytest.raises(WatsonxProblem):
        _verified_reply(chat, (), expected)
    with pytest.raises(WatsonxProblem):
        _verified_reply(chat, (record, record), expected)
    with pytest.raises(WatsonxProblem):
        _verified_reply(chat, (record,), expected.model_copy(update={"execution_code": "unexpected"}))
    wrong = Choice(message=Message(content='{"decision":"유지","evidence_ids":[]}'))
    with pytest.raises(WatsonxProblem):
        _verified_reply(chat.model_copy(update={"choices": (wrong,)}), (record,), expected)
