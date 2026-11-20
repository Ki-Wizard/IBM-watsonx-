"""IBM watsonx.ai Foundation Model generation and Governance groundedness checks."""
from __future__ import annotations

import json
import os
import re
import socket
from dataclasses import dataclass
from typing import Final, Literal

import httpx2
from pydantic import BaseModel, SecretStr, ValidationError

from .contract import KST, Result
from .watsonx import IAM, Token

DEFAULT_WATSONX_URL: Final = "https://us-south.ml.cloud.ibm.com"
DEFAULT_MODEL_ID: Final = "ibm/granite-3-8b-instruct"
DEFAULT_EMBED_MODEL_ID: Final = "intfloat/multilingual-e5-large"
_API_VERSION: Final = "2024-05-01"
_UNCONFIRMED_TEMP: Final = re.compile(r"(?<!\d)(?:[1-3]?\d(?:\.\d+)?)\s*(?:℃|°C|도)(?!\s*확인)")


@dataclass(frozen=True, slots=True)
class WatsonxAISettings:
    url: str
    api_key: SecretStr
    project_id: str
    model_id: str
    embed_model_id: str

    @classmethod
    def from_env(cls) -> WatsonxAISettings | None:
        api_key = (os.getenv("WATSONX_AI_API_KEY") or os.getenv("WXO_API_KEY") or "").strip()
        project_id = os.getenv("WATSONX_AI_PROJECT_ID", "").strip()
        if not api_key or not project_id:
            return None
        url = (os.getenv("WATSONX_AI_URL") or DEFAULT_WATSONX_URL).strip().rstrip("/")
        model_id = (os.getenv("WATSONX_AI_MODEL_ID") or DEFAULT_MODEL_ID).strip()
        embed_model_id = (os.getenv("WATSONX_AI_EMBED_MODEL_ID") or DEFAULT_EMBED_MODEL_ID).strip()
        return cls(
            url=url,
            api_key=SecretStr(api_key),
            project_id=project_id,
            model_id=model_id,
            embed_model_id=embed_model_id,
        )


class ChannelNotices(BaseModel):
    sms_alert: str
    official_memo: str
    public_notice: str
    used_watsonx_ai: bool = False
    model_id: str = "template-fallback"


@dataclass(frozen=True, slots=True)
class GovernanceCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class GovernanceReport:
    groundedness_score: float
    hallucination_risk: Literal["낮음", "보통", "높음"]
    checks: tuple[GovernanceCheck, ...]
    summary: str


def _client(base_url: str) -> httpx2.Client:
    transport = httpx2.HTTPTransport(
        http2=True,
        retries=2,
        limits=httpx2.Limits(max_connections=20, max_keepalive_connections=5),
        socket_options=[(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)],
    )
    return httpx2.Client(
        base_url=base_url,
        transport=transport,
        timeout=httpx2.Timeout(connect=5, read=25, write=10, pool=10),
    )


def _iam_token(client: httpx2.Client, api_key: SecretStr) -> str:
    resp = client.post(
        IAM,
        data={
            "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
            "apikey": api_key.get_secret_value(),
        },
    ).raise_for_status()
    return Token.model_validate_json(resp.content).access_token.get_secret_value()


def generate_text(prompt: str, settings: WatsonxAISettings, *, max_new_tokens: int = 500) -> str:
    """Call IBM watsonx.ai Text Generation REST API."""
    with _client(settings.url) as client:
        token = _iam_token(client, settings.api_key)
        resp = client.post(
            f"/ml/v1/text/generation?version={_API_VERSION}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "model_id": settings.model_id,
                "project_id": settings.project_id,
                "input": prompt,
                "parameters": {
                    "decoding_method": "greedy",
                    "max_new_tokens": max_new_tokens,
                    "repetition_penalty": 1.05,
                },
            },
        ).raise_for_status()
        payload = resp.json()
        results = payload.get("results") or []
        if not results or not isinstance(results[0].get("generated_text"), str):
            raise ValueError("watsonx.ai response did not include generated_text")
        return results[0]["generated_text"].strip()


def embed_texts(texts: list[str], settings: WatsonxAISettings) -> list[list[float]]:
    """Call IBM watsonx.ai Text Embeddings REST API."""
    if not texts:
        return []
    with _client(settings.url) as client:
        token = _iam_token(client, settings.api_key)
        resp = client.post(
            f"/ml/v1/text/embeddings?version={_API_VERSION}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "model_id": settings.embed_model_id,
                "project_id": settings.project_id,
                "inputs": texts,
            },
        ).raise_for_status()
        payload = resp.json()
        return [item["embedding"] for item in payload.get("results", [])]


def _fallback_notices(result: Result, manual_guidance: str | None) -> ChannelNotices:
    regional_cur = result.regional_alert.current if result.regional_alert else "확인 필요"
    gov_cur = result.government_alert.current if result.government_alert else "확인 필요"
    as_of_str = result.as_of.astimezone(KST).strftime("%Y-%m-%d %H:%M KST")
    guide_line = manual_guidance or "양식장 산소공급기 점검 및 현장 예찰을 강화해 주시기 바랍니다."

    if result.decision == "확인 필요":
        sms = (
            f"[수협 적조안내] {result.region} 특보 확인 필요({as_of_str}). "
            "공식 발표 세부 범위 확인 중이니 추가 안내 전까지 기존 대비태세를 유지하세요."
        )
        memo = (
            f"1. 기준시각: {as_of_str}\n"
            f"2. 대상해역: {result.region}\n"
            f"3. 판정결과: 확인 필요 ({result.reason})\n"
            "4. 조치사항: 공식 원문 추가 확인 후 후속 공문 발송 예정."
        )
        public = (
            f"[{result.region} 적조 특보 확인 안내] {as_of_str} 기준 공식 발표의 세부 적용 범위를 확인 중입니다. "
            "수온 실측값은 현장 확인이 필요하며, 확정 즉시 재안내하겠습니다."
        )
    else:
        sms = (
            f"[수협 적조안내] {result.region} 해역 '{regional_cur}', 정부 위기경보 '{gov_cur}'({as_of_str}). "
            f"{guide_line}"
        )
        memo = (
            f"제목: {result.region} 적조 특보 안내문 ({result.decision})\n"
            f"1. 기준시각: {as_of_str}\n"
            f"2. 해역 적조 특보: {regional_cur} (직전: {result.regional_alert.previous if result.regional_alert else '-'})\n"
            f"3. 정부 위기경보: {gov_cur} (직전: {result.government_alert.previous if result.government_alert else '-'})\n"
            f"4. 수온 정보: {result.water_temperature.status} (실측 수온 임의 기재 금지)\n"
            f"5. 현장 대응 권고: {guide_line}"
        )
        public = (
            f"{result.region} 적조 특보는 '{regional_cur}', 정부 위기경보는 '{gov_cur}' 단계입니다({as_of_str} 기준). "
            f"당시 {result.region} 수온은 확인이 필요합니다. 어업인께서는 {guide_line}"
        )
    return ChannelNotices(
        sms_alert=sms,
        official_memo=memo,
        public_notice=public,
        used_watsonx_ai=False,
        model_id="deterministic-template",
    )


def generate_channel_notices(
    result: Result,
    *,
    manual_guidance: str | None = None,
    settings: WatsonxAISettings | None = None,
) -> ChannelNotices:
    """Generate multi-channel notices via watsonx.ai with deterministic fallback."""
    active_settings = settings if settings is not None else WatsonxAISettings.from_env()
    if active_settings is None:
        return _fallback_notices(result, manual_guidance)

    regional_cur = result.regional_alert.current if result.regional_alert else "확인 필요"
    gov_cur = result.government_alert.current if result.government_alert else "확인 필요"
    evidence_lines = "\n".join(
        f"- [{item.publisher}] {item.title}: {item.summary}" for item in result.evidence
    ) or "- 확인된 공식 원문 없음"
    as_of_str = result.as_of.astimezone(KST).strftime("%Y-%m-%d %H:%M KST")

    prompt = (
        "너는 수협 중앙회 재난대응 AI 어시스턴트다. 아래 확인된 공식 근거만 사용해 3가지 채널 안내문을 한국어 JSON으로 작성하라.\n"
        "규칙:\n"
        "1) 해역명, 해역 특보 단계, 정부 위기경보 단계를 임의로 바꾸지 말 것.\n"
        "2) 수온은 확인되지 않았으므로 절대 구체적 숫자(예: 25℃)를 적지 말고 '확인 필요'로만 표기할 것.\n"
        "3) 반드시 JSON 객체만 출력: {\"sms_alert\":\"...\",\"official_memo\":\"...\",\"public_notice\":\"...\"}\n\n"
        f"해역: {result.region}\n"
        f"기준시각: {as_of_str}\n"
        f"판정: {result.decision}\n"
        f"해역 특보: {regional_cur}\n"
        f"정부 위기경보: {gov_cur}\n"
        f"대응 매뉴얼: {manual_guidance or '없음'}\n"
        f"공식 근거:\n{evidence_lines}\n"
    )
    try:
        raw = generate_text(prompt, active_settings, max_new_tokens=700)
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.DOTALL | re.IGNORECASE)
        body = json.loads(fenced[1] if fenced else raw)
        return ChannelNotices(
            sms_alert=str(body["sms_alert"]).strip(),
            official_memo=str(body["official_memo"]).strip(),
            public_notice=str(body["public_notice"]).strip(),
            used_watsonx_ai=True,
            model_id=active_settings.model_id,
        )
    except (httpx2.HTTPError, ValidationError, ValueError, KeyError, json.JSONDecodeError):
        return _fallback_notices(result, manual_guidance)


def evaluate_groundedness(result: Result, notices: ChannelNotices) -> GovernanceReport:
    """Run watsonx.governance-style faithfulness & hallucination guardrails."""
    combined = f"{notices.sms_alert}\n{notices.official_memo}\n{notices.public_notice}"
    checks: list[GovernanceCheck] = []

    region_ok = result.region in combined
    checks.append(GovernanceCheck(
        name="해역명 정확성",
        passed=region_ok,
        detail=f"요청 해역 '{result.region}'이 안내문에 정확히 포함됨" if region_ok else "해역명 누락 또는 불일치",
    ))

    if result.regional_alert is not None and result.regional_alert.current != "확인 필요":
        reg_ok = result.regional_alert.current in combined
        checks.append(GovernanceCheck(
            name="해역 특보 단계 일치",
            passed=reg_ok,
            detail=f"공식 단계 '{result.regional_alert.current}' 일치" if reg_ok else "해역 특보 단계 불일치",
        ))

    if result.government_alert is not None and result.government_alert.current != "확인 필요":
        gov_ok = result.government_alert.current in combined
        checks.append(GovernanceCheck(
            name="정부 위기경보 일치",
            passed=gov_ok,
            detail=f"공식 단계 '{result.government_alert.current}' 일치" if gov_ok else "정부 위기경보 단계 불일치",
        ))

    fabricated_temp = _UNCONFIRMED_TEMP.search(combined)
    temp_ok = fabricated_temp is None
    checks.append(GovernanceCheck(
        name="미확인 수온 환각 차단",
        passed=temp_ok,
        detail="실측 수온 미확인 원칙 준수" if temp_ok else f"미확인 수온 수치 탐지: {fabricated_temp.group(0)}",
    ))

    evidence_ok = bool(result.evidence) or result.decision == "확인 필요"
    checks.append(GovernanceCheck(
        name="공식 출처 연결성",
        passed=evidence_ok,
        detail=f"공식 근거 {len(result.evidence)}건 검증" if result.evidence else "근거 부재로 확인 필요 보류",
    ))

    passed_count = sum(1 for item in checks if item.passed)
    score = round((passed_count / len(checks)) * 100, 1) if checks else 100.0
    if score >= 95.0:
        risk: Literal["낮음", "보통", "높음"] = "낮음"
    elif score >= 75.0:
        risk = "보통"
    else:
        risk = "높음"

    summary = f"총 {len(checks)}개 거버넌스 항목 중 {passed_count}개 통과 (Groundedness {score:.1f}%)"
    return GovernanceReport(
        groundedness_score=score,
        hallucination_risk=risk,
        checks=tuple(checks),
        summary=summary,
    )
