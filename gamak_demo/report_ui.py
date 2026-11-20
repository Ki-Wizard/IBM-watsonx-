"""Render assessments, source citations, and the dated announcement timeline."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import assert_never

import streamlit as st

from .cloud_store import CloudSyncStatus, cloud_health_summary
from .collaborative import CollaborativeReview
from .contract import (
    Assessment,
    Draft,
    KST,
    Evidence,
    GovernmentAlert,
    RegionalAlert,
    Request,
    Result,
)
from .demo_ui import kst_label
from .evidence import GAMAK, GAMAK_NAMES, Announcement, ApprovedNotice, Archive, find_approval
from .hybrid_rag import HybridHit
from .rag import Passage, include_nifs_passage, retrieve
from .watsonx_ai import ChannelNotices, GovernanceReport

@dataclass(frozen=True, slots=True)
class Citation:
    number: int
    passage: Passage
    source: Evidence


def citations_for(
    request: Request, result: Result, collaboration: CollaborativeReview | None,
) -> dict[int, Citation]:
    passages = (
        collaboration.collaboration.citations
        if collaboration else include_nifs_passage(retrieve(request).passages, result)
    )
    sources = {source.id: source for source in result.evidence}
    citations: dict[int, Citation] = {}
    for number, topic, alert in (
        (1, "regional", result.regional_alert), (2, "government", result.government_alert),
    ):
        if alert is None or alert.evidence_id not in sources:
            continue
        passage = next(
            (item for item in passages if item.topic == topic and item.source_id == alert.evidence_id),
            None,
        )
        if passage:
            citations[number] = Citation(number, passage, sources[alert.evidence_id])
    return citations


def show_alert(
    label: str, alert: RegionalAlert | GovernmentAlert | None, citation: Citation | None,
) -> None:
    with st.container(border=True):
        if alert is None:
            st.metric(label, "확인 필요")
            return

        st.metric(label, alert.current)
        st.caption(f"승인본 {alert.previous}")
        if alert.effective_at is not None:
            issued = alert.effective_at.astimezone(KST).strftime("%m월 %d일 %H:%M 발령")
            st.html(f'<p class="gamak-caption">{issued}</p>')
        elif alert.current != "확인 필요":
            st.caption("발령시각 원문 미기재")
        if citation:
            st.markdown(f"[근거 {citation.number} 원문]({citation.source.url})")
            excerpt = citation.passage.text
            for phrase in ("대상 해역 중 “가막만”", " 단계를 발령", ", 14시부)"):
                excerpt = excerpt.replace(phrase, phrase.replace(" ", "\u00a0"))
            st.write(excerpt)
            st.caption(citation.passage.location)


_REGION_COORDS: Final[dict[str, tuple[float, float]]] = {
    "여수 가막만": (34.685, 127.675),
    "가막만": (34.685, 127.675),
}


def _alert_hex(level: str | None) -> str:
    return {
        "적조경보": "#DC2626",
        "적조주의보": "#F58220",
        "예비특보": "#EAB308",
        "해제": "#16A34A",
    }.get(level or "", "#64748B")


def show_region_map(result: Result) -> None:
    """Render a Gamak Bay status map."""
    lat, lon = _REGION_COORDS.get(result.region, (34.685, 127.675))
    level = result.regional_alert.current if result.regional_alert else "확인 필요"
    st.map(
        [{"lat": lat, "lon": lon}],
        zoom=10,
        size=1800,
        color=_alert_hex(level),
        height=220,
    )


def show_assessment(result: Result, citations: dict[int, Citation]) -> None:
    st.subheader(result.decision)
    banner_colors = {
        "갱신 필요": ("#FFF7ED", "#C2410C", "#FDBA74"),
        "유지": ("#F0FDF4", "#15803D", "#86EFAC"),
        "확인 필요": ("#FEFCE8", "#A16207", "#FDE047"),
    }
    bg, fg, border = banner_colors.get(result.decision, ("#F8FAFC", "#334155", "#CBD5E1"))
    st.html(
        f'<div style="background:{bg};border-left:5px solid {fg};border-top:1px solid {border};'
        f'border-right:1px solid {border};border-bottom:1px solid {border};'
        f'padding:0.85rem 1rem;border-radius:0.5rem;margin-bottom:0.75rem;color:{fg};font-weight:600;">'
        f'판정 결과 · {escape(result.decision)} — {escape(result.reason)}</div>'
    )
    reason = result.reason.replace("정부 위기경보", "정부\u00a0위기경보")
    match result.decision:
        case "갱신 필요":
            st.warning(reason)
        case "유지":
            st.success(reason)
        case "확인 필요":
            st.warning(reason)
        case _ as unreachable:
            assert_never(unreachable)

    regional, government, map_col = st.columns([1, 1, 1.1])
    with regional:
        show_alert("해역 적조 특보", result.regional_alert, citations.get(1))
    with government:
        show_alert("정부 위기경보", result.government_alert, citations.get(2))
    with map_col, st.container(border=True):
        st.caption(f"해역 위치 · {result.region}")
        show_region_map(result)

    if result.evidence:
        st.subheader("공식 원문")
        links = st.columns(2) if len(result.evidence) > 1 else [st.container()]
        for index, source in enumerate(result.evidence):
            links[index % len(links)].markdown(f"[{source.title}]({source.url}) · {source.publisher}")
    st.markdown(f"**수온** · {result.water_temperature.status}")
    if result.evidence:
        with st.expander("발표 요약"):
            for source in result.evidence:
                st.write(source.summary)


def show_workflow(result: Result, collaboration: CollaborativeReview | None, status: str) -> None:
    research = "원문 확인" if result.evidence else "확인 가능한 근거 없음"
    for column, label, status in zip(
        st.columns(3), ("근거 조사", "당직 지원", "승인함"),
        (research, result.decision, status), strict=True,
    ):
        with column, st.container(border=True):
            st.markdown(f"**{label}**")
            st.write(status)
    if collaboration:
        trace = collaboration.collaboration
        with st.expander("두 에이전트의 인계 요약"):
            st.caption("당직 지원 에이전트 → 근거 조사 에이전트 → 공식 원문 검색")
            if trace.nifs and trace.nifs.status == "checked":
                step = "목록 → 상세" if trace.nifs.bulletin else "목록"
                st.caption(f"국립수산과학원 적조속보 · {step}")
            if trace.citations:
                observations = ", ".join(
                    f"{passage.level} ({passage.source_id})" for passage in trace.citations
                )
                st.write(f"근거 조사 에이전트가 확인한 최신 근거는 {observations}입니다.")
            else:
                st.write("근거 조사 에이전트가 이 요청에서 인용 가능한 원문을 찾지 못했습니다.")
            proposal = result.decision.replace(" ", "\u00a0")
            st.write(f"당직 지원 제안 · **{proposal}**")
            st.caption(f"IBM 실행 이력 ID {trace.trace_id or trace.thread_id}")


def _notice_body(
    text: str, regional: Evidence | None, government: Evidence | None,
) -> None:
    first, government_start, remainder = escape(text).partition(" 정부 ")
    second, water_start, third = remainder.partition(" 당시 ")
    for part, source, label in (
        (first, regional, "해역 특보"), (government_start + second, government, "정부 위기경보"),
    ):
        if part:
            st.html(f'<p class="gamak-draft">{part.strip()}</p>')
        if source:
            st.markdown(f"[{label} 원문]({source.url})")
    if water_start:
        st.html(f'<p class="gamak-draft">{(water_start + third).strip()}</p>')


def show_notice_comparison(archive: Archive, request: Request, result: Assessment, draft: Draft) -> None:
    st.subheader("기존 안내와 새 초안")
    approved, proposed = st.columns(2)
    notice = find_approval(archive, request)
    with approved, st.container(border=True):
        st.markdown("**기존 안내**")
        if notice:
            st.caption(f"가상 승인본 · {kst_label(notice.approved_at)}")
            _notice_body(notice.text, *_baseline_sources(archive, notice))
        else:
            st.caption("보관된 승인본을 찾을 수 없습니다.")
    sources = {source.id: source for source in result.evidence}
    with proposed, st.container(border=True):
        st.markdown("**새 초안**")
        st.caption(f"판정 기준 · {kst_label(request.as_of)}")
        _notice_body(
            draft.text,
            sources.get(result.regional_alert.evidence_id) if result.regional_alert else None,
            sources.get(result.government_alert.evidence_id) if result.government_alert else None,
        )


def _baseline_sources(archive: Archive, notice: ApprovedNotice) -> tuple[Evidence | None, Evidence | None]:
    documents = [item for item in archive.documents if item.source.id in notice.evidence_ids]
    regional = next((
        item.source for item in documents
        if item.regional_alert.value == notice.regional_alert
        and item.regional_alert.effective_at == notice.regional_effective_at
    ), None)
    government = next((
        item.source for item in documents
        if item.government_alert.value == notice.government_alert
        and item.government_alert.effective_at == notice.government_effective_at
    ), None)
    return regional, government


def _timeline_status(
    request: Request, result: Result | None, item: Announcement,
    issued_at: datetime | None, alert: RegionalAlert | GovernmentAlert | None,
    baseline: Evidence | None,
) -> str:
    if item.source.published_at > request.as_of:
        return "조회 전"
    if issued_at and issued_at > request.as_of:
        return "발령 전"
    if result is None:
        return "조회 가능 · 판단 요청 전"
    if alert and alert.evidence_id == item.source.id:
        return "범위 확인에 참고" if alert.current == "확인 필요" else "판정에 반영"
    if baseline == item.source and item.source in result.evidence:
        return "승인본 비교 근거"
    return "조회 가능 · 판정 미반영"


def show_timeline(archive: Archive, request: Request, result: Result | None) -> None:
    st.subheader("해역별 발표 타임라인")
    st.text(f"{request.region} · 기준시각 {kst_label(request.as_of)}")
    if request.region not in GAMAK_NAMES:
        st.info("보관 발표에서 이 해역의 특보를 확인할 수 없습니다.")
        return
    st.caption("자료 조회 가능시각은 시연 자료의 기준입니다. 발령시각은 원문에 명시된 시각입니다.")
    approved = find_approval(archive, request)
    baseline_sources = _baseline_sources(archive, approved) if approved else (None, None)
    for index, (column, label) in enumerate(zip(
        st.columns(2), ("해역 적조 특보", "정부 위기경보"), strict=True,
    )):
        with column:
            st.markdown(f"**{label}**")
            for item in sorted(archive.documents, key=lambda row: row.source.published_at):
                if GAMAK not in item.regions:
                    continue
                issued = item.regional_alert if index == 0 else item.government_alert
                alert = (result.regional_alert if index == 0 else result.government_alert) if result else None
                at = kst_label(issued.effective_at) if issued.effective_at else "원문 미기재"
                with st.container(border=True):
                    st.markdown(f"**{issued.value}**")
                    st.caption(f"자료 조회 가능시각 · {kst_label(item.source.published_at)}")
                    st.caption(f"발령시각 · {at}")
                    st.write(_timeline_status(
                        request, result, item, issued.effective_at, alert, baseline_sources[index],
                    ))
                    st.markdown(f"[공식 발표 원문]({item.source.url})")
            if index == 0 and result:
                for source in result.evidence:
                    if source.publisher == "국립수산과학원":
                        with st.container(border=True):
                            st.markdown("**해제 · 국립수산과학원**")
                            st.caption(f"자료 조회 가능 기준 · {kst_label(source.published_at)}")
                            st.caption("등록일을 기준으로 다음 날 00시부터 반영 · 발령시각 원문 미기재")
                            st.write("판정에 반영")
                            st.markdown(f"[적조속보 원문]({source.url})")


def show_cloud_sidebar() -> None:
    """Display IBM watsonx and IBM Cloud service connection status in the sidebar."""
    with st.sidebar:
        st.divider()
        st.subheader("IBM watsonx · Cloud 연동")
        for svc in cloud_health_summary():
            icon = "🟢" if svc.configured else "⚪"
            st.caption(f"{icon} **{svc.name}** · {svc.detail}")


def show_ai_governance_and_channels(
    notices: ChannelNotices | None,
    governance: GovernanceReport | None,
    manual_hits: tuple[HybridHit, ...],
    cloud_sync: CloudSyncStatus | None,
) -> None:
    """Render watsonx.ai multi-channel outputs, Governance score, and Hybrid RAG guidance."""
    if notices is None or governance is None:
        return

    st.subheader("watsonx.ai 다중 채널 안내문 & 거버넌스 검증")
    col_score, col_risk, col_model = st.columns(3)
    col_score.metric("근거 일치율 (Groundedness)", f"{governance.groundedness_score:.1f}%")
    col_risk.metric("환각 위험도", governance.hallucination_risk)
    col_model.metric("생성 엔진", notices.model_id if notices.used_watsonx_ai else "로컬 폴백 템플릿")

    if cloud_sync and cloud_sync.status == "synced":
        st.success(cloud_sync.detail)

    sms_tab, memo_tab, public_tab, gov_tab = st.tabs(
        ["어업인 SMS", "유관기관 공문", "홈페이지 공지", "거버넌스 · 매뉴얼 RAG"],
    )
    with sms_tab:
        st.text_area("어업인 발송용 SMS/알림톡", value=notices.sms_alert, height=110, key="wx_sms")
    with memo_tab:
        st.text_area("지자체·해수부 보고용 공문 초안", value=notices.official_memo, height=170, key="wx_memo")
    with public_tab:
        st.text_area("수협 홈페이지·SNS 공지문", value=notices.public_notice, height=130, key="wx_public")
    with gov_tab:
        st.caption(governance.summary)
        for check in governance.checks:
            mark = "✅" if check.passed else "❌"
            st.write(f"{mark} **{check.name}** — {check.detail}")
        if manual_hits:
            st.divider()
            st.markdown(f"**대응 매뉴얼 Hybrid RAG** (`{manual_hits[0].method}`)")
            for hit in manual_hits:
                with st.container(border=True):
                    st.markdown(f"**{hit.entry.title}** (유사도 `{hit.score:.2f}`)")
                    st.write(hit.entry.content)

    report_md = (
        f"# 수협 적조 안내 다중 채널 리포트\n\n"
        f"- Groundedness: {governance.groundedness_score:.1f}% (환각 위험도: {governance.hallucination_risk})\n"
        f"- 생성 엔진: {notices.model_id if notices.used_watsonx_ai else '로컬 폴백 템플릿'}\n\n"
        f"## 1. 어업인 SMS/알림톡\n{notices.sms_alert}\n\n"
        f"## 2. 유관기관 공문 초안\n{notices.official_memo}\n\n"
        f"## 3. 홈페이지·SNS 공지문\n{notices.public_notice}\n"
    )
    st.download_button(
        "다중 채널 안내문 리포트 다운로드 (.md)",
        data=report_md.encode("utf-8"),
        file_name="gamak-red-tide-notices.md",
        mime="text/markdown",
        key="download_notices_md",
    )

