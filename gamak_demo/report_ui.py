"""Render assessments, source citations, and the dated announcement timeline."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import assert_never

import streamlit as st

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
from .rag import Passage, include_nifs_passage, retrieve

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


def show_assessment(result: Result, citations: dict[int, Citation]) -> None:
    st.subheader(result.decision)
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

    regional, government = st.columns(2)
    with regional:
        show_alert("해역 적조 특보", result.regional_alert, citations.get(1))
    with government:
        show_alert("정부 위기경보", result.government_alert, citations.get(2))

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
