"""IBM Cloudant & Object Storage integration for shared approval inbox and audit archival."""
from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final, Literal

import httpx2
from pydantic import SecretStr

from .contract import Result
from .ledger import ReviewNote
from .watsonx import IAM, Token
from .watsonx_ai import GovernanceReport, WatsonxAISettings

DEFAULT_CLOUDANT_DB: Final = "gamak_approvals"


@dataclass(frozen=True, slots=True)
class CloudantSettings:
    url: str
    api_key: SecretStr
    database: str

    @classmethod
    def from_env(cls) -> CloudantSettings | None:
        url = os.getenv("CLOUDANT_URL", "").strip().rstrip("/")
        api_key = os.getenv("CLOUDANT_APIKEY", "").strip()
        if not url or not api_key:
            return None
        db = os.getenv("CLOUDANT_DB", DEFAULT_CLOUDANT_DB).strip() or DEFAULT_CLOUDANT_DB
        return cls(url=url, api_key=SecretStr(api_key), database=db)


@dataclass(frozen=True, slots=True)
class CosSettings:
    endpoint: str
    bucket: str
    api_key: SecretStr

    @classmethod
    def from_env(cls) -> CosSettings | None:
        endpoint = os.getenv("COS_ENDPOINT", "").strip().rstrip("/")
        bucket = os.getenv("COS_BUCKET", "").strip()
        api_key = os.getenv("COS_APIKEY", "").strip()
        if not endpoint or not bucket or not api_key:
            return None
        return cls(endpoint=endpoint, bucket=bucket, api_key=SecretStr(api_key))


@dataclass(frozen=True, slots=True)
class CloudSyncStatus:
    service: str
    status: Literal["synced", "skipped", "error"]
    detail: str


@dataclass(frozen=True, slots=True)
class ServiceHealth:
    name: str
    configured: bool
    detail: str


def _iam_token(client: httpx2.Client, api_key: SecretStr) -> str:
    resp = client.post(
        IAM,
        data={
            "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
            "apikey": api_key.get_secret_value(),
        },
    ).raise_for_status()
    return Token.model_validate_json(resp.content).access_token.get_secret_value()


def sync_result_to_cloudant(
    result: Result,
    *,
    note: ReviewNote | None = None,
    governance: GovernanceReport | None = None,
    settings: CloudantSettings | None = None,
) -> CloudSyncStatus:
    """Mirror a review result into IBM Cloudant so teams share one cloud inbox."""
    active = settings if settings is not None else CloudantSettings.from_env()
    if active is None:
        return CloudSyncStatus("IBM Cloudant", "skipped", "CLOUDANT_URL/APIKEY 미설정 (로컬 SQLite 사용)")

    doc = {
        "type": "gamak_review",
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "result": result.model_dump(mode="json"),
        "note": note.model_dump(mode="json") if note else None,
        "governance": {
            "groundedness_score": governance.groundedness_score,
            "hallucination_risk": governance.hallucination_risk,
        }
        if governance
        else None,
    }
    transport = httpx2.HTTPTransport(
        http2=True,
        retries=2,
        socket_options=[(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)],
    )
    try:
        with httpx2.Client(base_url=active.url, transport=transport, timeout=10.0) as client:
            token = _iam_token(client, active.api_key)
            resp = client.post(
                f"/{active.database}",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=doc,
            ).raise_for_status()
            doc_id = resp.json().get("id", "unknown")
            return CloudSyncStatus("IBM Cloudant", "synced", f"클라우드 승인함 동기화 완료 (id: {doc_id})")
    except (httpx2.HTTPError, ValueError) as exc:
        return CloudSyncStatus("IBM Cloudant", "error", f"Cloudant 동기화 보류: {type(exc).__name__}")


def archive_report_to_cos(
    object_key: str,
    payload: bytes,
    *,
    settings: CosSettings | None = None,
) -> CloudSyncStatus:
    """Archive an official review JSON/Markdown report into IBM Cloud Object Storage."""
    active = settings if settings is not None else CosSettings.from_env()
    if active is None:
        return CloudSyncStatus("IBM Cloud Object Storage", "skipped", "COS_ENDPOINT/BUCKET/APIKEY 미설정")

    transport = httpx2.HTTPTransport(http2=True, retries=2)
    try:
        with httpx2.Client(base_url=active.endpoint, transport=transport, timeout=10.0) as client:
            token = _iam_token(client, active.api_key)
            client.put(
                f"/{active.bucket}/{object_key.lstrip('/')}",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                content=payload,
            ).raise_for_status()
            return CloudSyncStatus("IBM Cloud Object Storage", "synced", f"COS 아카이브 저장 완료 ({object_key})")
    except httpx2.HTTPError as exc:
        return CloudSyncStatus("IBM Cloud Object Storage", "error", f"COS 저장 보류: {type(exc).__name__}")


def cloud_health_summary() -> tuple[ServiceHealth, ...]:
    """Summarize which IBM watsonx and IBM Cloud services are configured in this runtime."""
    wxo_ok = bool(os.getenv("WXO_ENDPOINT_URL", "").strip() and os.getenv("WXO_API_KEY", "").strip())
    wx_ai = WatsonxAISettings.from_env()
    cloudant = CloudantSettings.from_env()
    cos = CosSettings.from_env()
    nifs_ok = bool(os.getenv("NIFS_RED_TIDE_API_KEY", "").strip())

    return (
        ServiceHealth("watsonx Orchestrate", wxo_ok, "멀티에이전트 협업 연결됨" if wxo_ok else "로컬 시연 모드"),
        ServiceHealth(
            "watsonx.ai",
            wx_ai is not None,
            f"모델 {wx_ai.model_id}" if wx_ai else "템플릿 폴백 모드",
        ),
        ServiceHealth(
            "IBM Cloudant",
            cloudant is not None,
            f"DB '{cloudant.database}'" if cloudant else "로컬 SQLite 사용",
        ),
        ServiceHealth(
            "IBM COS",
            cos is not None,
            f"버킷 '{cos.bucket}'" if cos else "미설정",
        ),
        ServiceHealth("국립수산과학원 API", nifs_ok, "실시간 적조속보 연결됨" if nifs_ok else "보관 자료 사용"),
    )
