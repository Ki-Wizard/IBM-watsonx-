"""Call the deployed agent, verify its tool trace, and use the common inbox."""
from __future__ import annotations

import json
import os
import re
import socket
from dataclasses import dataclass, replace
from pathlib import Path
from secrets import token_hex
from typing import Final, assert_never
from uuid import UUID

import httpx2
from pydantic import BaseModel, SecretStr, TypeAdapter, ValidationError

from .agent_contract import (
    AGENT_NAME,
    TOOL_NAME,
    AgentProposal,
    AgentReply,
    execution_code,
)
from .contract import Request, Result
from .ledger import ReviewNote
from .service import finalize, prepare

IAM: Final = "https://iam.cloud.ibm.com/identity/token"
_AGENTS: Final = "/v1/orchestrate/agents"


class WatsonxProblem(RuntimeError):
    """A sanitized diagnostic that is safe to show on the rehearsal screen."""


@dataclass(frozen=True, slots=True)
class Settings:
    endpoint: str
    key: SecretStr
    agent_name: str

    @classmethod
    def from_env(cls) -> Settings:
        endpoint = os.getenv("WXO_ENDPOINT_URL", "").strip().rstrip("/")
        key = os.getenv("WXO_API_KEY", "").strip()
        name = os.getenv("WXO_AGENT_NAME", "").strip() or AGENT_NAME
        if not endpoint or not key:
            message = "IBM 교육 계정 연결 설정이 비어 있습니다."
            raise WatsonxProblem(message)

        allowed_url = r"https://api\.[a-z0-9-]+\.watson-orchestrate\.cloud\.ibm\.com/instances/[a-zA-Z0-9_-]+"
        if not re.fullmatch(allowed_url, endpoint):
            message = "IBM Orchestrate의 교육 계정 서비스 주소를 확인해 주세요."
            raise WatsonxProblem(message)
        return cls(endpoint, SecretStr(key), name)


class Token(BaseModel):
    access_token: SecretStr


class Agent(BaseModel):
    id: UUID
    name: str


class AgentList(BaseModel):
    agents: tuple[Agent, ...] = ()
    assistants: tuple[Agent, ...] = ()


class Message(BaseModel):
    content: str


class Choice(BaseModel):
    message: Message


class Chat(BaseModel):
    thread_id: UUID
    choices: tuple[Choice, ...]
    trace_id: str | None = None


class Step(BaseModel):
    type: str
    name: str | None = None
    content: str | None = None
    tool_call_id: str | None = None


class StepGroup(BaseModel):
    step_details: tuple[Step, ...]


class History(BaseModel):
    role: str
    step_history: tuple[StepGroup, ...] | None = None


@dataclass(frozen=True, slots=True)
class AgentRun:
    chat: Chat
    history: tuple[History, ...]


_AGENT_LIST: Final = TypeAdapter(tuple[Agent, ...] | AgentList)
_HISTORY: Final = TypeAdapter(tuple[History, ...])


def _connect(endpoint: str) -> httpx2.Client:
    transport = httpx2.HTTPTransport(
        http2=True, retries=3,
        limits=httpx2.Limits(max_connections=200, max_keepalive_connections=40, keepalive_expiry=30),
        socket_options=[(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)],
    )
    return httpx2.Client(
        base_url=endpoint, transport=transport,
        timeout=httpx2.Timeout(connect=5, read=30, write=10, pool=10),
    )


def proposal_json(chat: Chat) -> str:
    if not chat.choices:
        message = "IBM 에이전트 응답이 비어 있습니다."
        raise WatsonxProblem(message)
    content = chat.choices[0].message.content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", content, flags=re.DOTALL | re.IGNORECASE)
    return fenced[1] if fenced else content


def _verified_reply(
    chat: Chat, history: tuple[History, ...], expected: AgentReply,
) -> AgentReply:
    traces = [
        step.content
        for message in history if message.role == "assistant"
        for group in message.step_history or ()
        for step in group.step_details
        if step.type == "tool_response" and step.name == TOOL_NAME
    ]
    if len(traces) != 1 or traces[0] is None:
        message = "IBM 대화 이력에서 공식 근거 도구의 실행 결과를 확인할 수 없습니다."
        raise WatsonxProblem(message)

    proposal = AgentProposal.model_validate_json(proposal_json(chat))
    actual_tool_reply = AgentReply.model_validate_json(traces[0])
    evidence_ids = sorted(source.id for source in expected.assessment.evidence)
    if (
        actual_tool_reply != expected
        or proposal.decision != expected.assessment.decision
        or sorted(proposal.evidence_ids) != evidence_ids
    ):
        message = "IBM 응답과 시연 공식 근거가 일치하지 않습니다."
        raise WatsonxProblem(message)
    return actual_tool_reply


def run_agent(request_text: str, settings: Settings) -> AgentRun:
    """Call a deployed agent and fetch its real IBM conversation history."""
    try:
        with _connect(settings.endpoint) as client:
            auth = client.post(IAM, data={
                "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                "apikey": settings.key.get_secret_value(),
            }).raise_for_status()
            token = Token.model_validate_json(auth.content)
            client.headers["Authorization"] = f"Bearer {token.access_token.get_secret_value()}"
            # A relative route retains the instance prefix in the configured base URL.
            index = client.get(_AGENTS.lstrip("/")).raise_for_status()
            catalog = _AGENT_LIST.validate_json(index.content)
            match catalog:
                case AgentList(agents=agents, assistants=assistants):
                    records = agents or assistants
                case tuple() as records:
                    pass
                case _ as unreachable:
                    assert_never(unreachable)
            agent = next((item for item in records if item.name == settings.agent_name), None)
            if agent is None:
                message = "배포된 가막만 IBM 에이전트를 찾을 수 없습니다."
                raise WatsonxProblem(message)

            answer = client.post(f"v1/orchestrate/{agent.id}/chat/completions", json={
                "messages": [{"role": "user", "content": request_text}],
                "stream": False,
            }).raise_for_status()
            chat = Chat.model_validate_json(answer.content)
            trace = client.get(f"v1/orchestrate/threads/{chat.thread_id}/messages").raise_for_status()
            return AgentRun(chat, _HISTORY.validate_json(trace.content))
    except httpx2.HTTPStatusError as exc:
        message = f"IBM 서비스 호출에 실패했습니다 (HTTP {exc.response.status_code})."
        raise WatsonxProblem(message) from None
    except httpx2.RequestError:
        message = "IBM 서비스에 연결할 수 없습니다."
        raise WatsonxProblem(message) from None
    except ValidationError:
        message = "IBM 응답이 공통 JSON 형식과 일치하지 않습니다."
        raise WatsonxProblem(message) from None


def review_watsonx(request: Request, db: Path, *, note: ReviewNote | None = None) -> Result:
    """Write a draft only after validating the IBM JSON response and real tool trace."""
    settings = Settings.from_env()
    prepared = prepare(request)
    challenge = token_hex(16)
    expected = AgentReply(
        assessment=prepared.assessment, execution_code=execution_code(challenge),
    )
    request_text = json.dumps(
        {"request_json": request.model_dump_json(), "challenge": challenge}, ensure_ascii=False,
    )
    run = run_agent(request_text, settings)
    try:
        verified = _verified_reply(run.chat, run.history, expected)
    except ValidationError:
        message = "IBM 응답이 공통 JSON 형식과 일치하지 않습니다."
        raise WatsonxProblem(message) from None
    return finalize(replace(prepared, assessment=verified.assessment), db, "watsonx", note=note)
