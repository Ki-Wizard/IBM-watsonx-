"""Tests for watsonx.ai multi-channel generation, Governance checks, Hybrid RAG, and IBM Cloudant."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pydantic import SecretStr
from pytest import MonkeyPatch

from gamak_demo.cloud_store import (
    CloudantSettings,
    cloud_health_summary,
    sync_result_to_cloudant,
)
from gamak_demo.contract import KST, NoticeId, Request
from gamak_demo.hybrid_rag import search_manual
from gamak_demo.service import review
from gamak_demo.watsonx_ai import (
    ChannelNotices,
    WatsonxAISettings,
    evaluate_groundedness,
    generate_channel_notices,
)


def _sample_result(tmp_path: Path):
    request = Request(
        region="여수 가막만",
        as_of=datetime(2025, 8, 29, 16, 30, tzinfo=KST),
        approved_notice_id=NoticeId("gamak-2025-08-26-demo"),
        question="오늘 16시 30분 기준으로 직전 승인본을 유지해도 되나요?",
    )
    return review(request, tmp_path / "test.sqlite3")


def test_channel_notices_fallback_and_governance_pass(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("WATSONX_AI_PROJECT_ID", raising=False)
    monkeypatch.delenv("WATSONX_AI_API_KEY", raising=False)
    result = _sample_result(tmp_path)

    notices = generate_channel_notices(result, manual_guidance="산소발생기 가동 및 야간 순찰 강화")
    assert not notices.used_watsonx_ai
    assert "여수 가막만" in notices.sms_alert
    assert "적조주의보" in notices.official_memo
    assert "경계" in notices.public_notice

    report = evaluate_groundedness(result, notices)
    assert report.groundedness_score == 100.0
    assert report.hallucination_risk == "낮음"
    assert all(check.passed for check in report.checks)


def test_governance_detects_hallucinated_temperature_and_missing_level(tmp_path: Path) -> None:
    result = _sample_result(tmp_path)
    bad_notices = ChannelNotices(
        sms_alert="여수 가막만 수온 26.5℃로 상승하여 주의가 필요합니다.",
        official_memo="여수 가막만 안내",
        public_notice="해역 특보 변경 안내",
        used_watsonx_ai=True,
        model_id="ibm/granite-3-8b-instruct",
    )
    report = evaluate_groundedness(result, bad_notices)
    assert report.groundedness_score < 75.0
    assert report.hallucination_risk == "높음"
    failed = {c.name for c in report.checks if not c.passed}
    assert "미확인 수온 환각 차단" in failed
    assert "해역 특보 단계 일치" in failed


def test_channel_notices_uses_watsonx_ai_when_configured(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    result = _sample_result(tmp_path)
    settings = WatsonxAISettings(
        url="https://us-south.ml.cloud.ibm.com",
        api_key=SecretStr("test-key"),
        project_id="proj-123",
        model_id="ibm/granite-3-8b-instruct",
        embed_model_id="intfloat/multilingual-e5-large",
    )

    def fake_generate(prompt: str, cfg: WatsonxAISettings, *, max_new_tokens: int = 500) -> str:
        assert "여수 가막만" in prompt
        assert cfg.project_id == "proj-123"
        return json.dumps({
            "sms_alert": "[수협] 여수 가막만 적조주의보·정부 위기경보 경계 발령. 수온 확인 필요.",
            "official_memo": "여수 가막만 적조주의보 및 정부 위기경보 경계 단계 보고(수온 확인 필요).",
            "public_notice": "여수 가막만 적조주의보, 정부 위기경보 경계 단계 안내드립니다. 수온은 확인 필요.",
        }, ensure_ascii=False)

    monkeypatch.setattr("gamak_demo.watsonx_ai.generate_text", fake_generate)
    notices = generate_channel_notices(result, settings=settings)
    assert notices.used_watsonx_ai is True
    assert notices.model_id == "ibm/granite-3-8b-instruct"
    assert evaluate_groundedness(result, notices).groundedness_score == 100.0


def test_hybrid_rag_retrieves_matching_manual_entry(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("WATSONX_AI_PROJECT_ID", raising=False)
    hits = search_manual("가막만 적조주의보 발령 시 양식장 대응 요령", levels=("적조주의보",), top_k=2)
    assert len(hits) == 2
    assert hits[0].entry.level == "적조주의보"
    assert hits[0].method == "hybrid-lexical"


def test_cloudant_sync_skips_cleanly_without_env(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("CLOUDANT_URL", raising=False)
    monkeypatch.delenv("CLOUDANT_APIKEY", raising=False)
    result = _sample_result(tmp_path)
    status = sync_result_to_cloudant(result)
    assert status.status == "skipped"


def test_cloudant_sync_posts_document_with_mock(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    result = _sample_result(tmp_path)
    notices = generate_channel_notices(result)
    gov = evaluate_groundedness(result, notices)

    class _FakeResponse:
        def __init__(self, payload: dict):
            self._payload = payload
            self.content = json.dumps(payload).encode("utf-8")

        def raise_for_status(self):
            return self

        def json(self):
            return self._payload

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, path: str, **kwargs):
            if "identity/token" in path:
                return _FakeResponse({"access_token": "iam-token-123"})
            assert path == "/gamak_approvals"
            assert kwargs["json"]["governance"]["groundedness_score"] == 100.0
            return _FakeResponse({"ok": True, "id": "doc-abc"})

    monkeypatch.setattr("gamak_demo.cloud_store.httpx2.Client", _FakeClient)
    cfg = CloudantSettings(url="https://example.cloudantnosqldb.appdomain.cloud", api_key=SecretStr("k"), database="gamak_approvals")
    status = sync_result_to_cloudant(result, governance=gov, settings=cfg)
    assert status.status == "synced"
    assert "doc-abc" in status.detail


def test_cloud_health_summary_reflects_env(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("WATSONX_AI_API_KEY", "k")
    monkeypatch.setenv("WATSONX_AI_PROJECT_ID", "p")
    summary = {item.name: item for item in cloud_health_summary()}
    assert summary["watsonx.ai"].configured is True
