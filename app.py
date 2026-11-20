"""가막만 적조 안내 갱신 판단 — Streamlit 시연 화면."""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Final, assert_never

import streamlit as st
from dotenv import load_dotenv
from pydantic import ValidationError

from gamak_demo.collaborative import CollaborativeReview, review_collaborative
from gamak_demo.contract import (
    KST,
    Evidence,
    GovernmentAlert,
    NoticeId,
    RegionalAlert,
    Request,
    Result,
)
from gamak_demo.ledger import draft_count
from gamak_demo.rag import Passage, retrieve
from gamak_demo.service import review
from gamak_demo.watsonx import WatsonxProblem, review_watsonx

REQUEST: Final = Path(__file__).resolve().parent / "examples" / "gamak-update.request.json"


@dataclass(frozen=True, slots=True)
class Citation:
    number: int
    passage: Passage
    source: Evidence


def citations_for(
    request: Request, result: Result, collaboration: CollaborativeReview | None,
) -> dict[int, Citation]:
    passages = collaboration.collaboration.citations if collaboration else retrieve(request).passages
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
            st.html(f'<span id="gamak-source-{citation.number}"></span>')
            st.markdown(f"[근거 {citation.number} 원문]({citation.source.url})")
            excerpt = citation.passage.text.replace("대상 해역 중", "대상\u00a0해역\u00a0중")
            st.write(excerpt.replace(", 14시부)", ",\u00a014시부)"))
            st.caption(citation.passage.location)


def show_assessment(result: Result, citations: dict[int, Citation]) -> None:
    st.subheader(result.decision)
    match result.decision:
        case "갱신 필요":
            st.warning(result.reason)
        case "유지":
            st.success(result.reason)
        case "확인 필요":
            st.warning(result.reason)
        case _ as unreachable:
            assert_never(unreachable)

    regional, government = st.columns(2)
    with regional:
        show_alert("해역 적조 특보", result.regional_alert, citations.get(1))
    with government:
        show_alert("정부 위기경보", result.government_alert, citations.get(2))

    if result.follow_up_question:
        st.warning(result.follow_up_question)

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


def show_inbox(result: Result, citations: dict[int, Citation]) -> None:
    st.subheader("승인함")
    ledger = result.ledger
    match ledger.action:
        case "created":
            note = "초안 1건 등록"
        case "reused":
            note = "기존 초안 재사용"
        case "none":
            note = "확인 이력 기록"
        case _ as unreachable:
            assert_never(unreachable)

    with st.container(border=True):
        st.metric("승인 대기 건수", f"{ledger.after}건")
        st.markdown(f"**승인함 {ledger.before} → {ledger.after}건** · {note}")

    if result.draft:
        st.subheader("승인 대기 초안")
        draft_text = escape(result.draft.text).replace("같은 날", "같은\u00a0날")
        if result.government_alert:
            stage = escape(f"‘{result.government_alert.current}’입니다.")
            draft_text = draft_text.replace(stage, f'<span class="gamak-stage">{stage}</span>')
        regional, government_source, remainder = draft_text.partition(" 정부 위기경보는 ")
        if government_source:
            government, water_source, water = remainder.partition(" 당시 ")
            if 1 in citations:
                regional += ' <sup><a href="#gamak-source-1" aria-label="근거 1">[1]</a></sup>'
            if 2 in citations:
                government += ' <sup><a href="#gamak-source-2" aria-label="근거 2">[2]</a></sup>'
            draft_text = f"{regional}{government_source}{government}{water_source}{water}"
        st.html(f'<p class="gamak-draft">{draft_text}</p>')
        with st.expander("초안 ID"):
            st.code(result.draft.id, language=None, wrap_lines=True)


def show_workflow(result: Result, collaboration: CollaborativeReview | None) -> None:
    research = "원문 확인" if result.evidence else "확인 가능한 근거 없음"
    approval = "승인 대기" if result.draft else "새 초안 없음"
    for column, label, status in zip(
        st.columns(3), ("근거 조사", "당직 지원", "승인함"),
        (research, result.decision, approval), strict=True,
    ):
        with column, st.container(border=True):
            st.markdown(f"**{label}**")
            st.write(status)
    if collaboration:
        trace = collaboration.collaboration
        with st.expander("두 에이전트의 인계 요약"):
            st.caption("당직 지원 에이전트 → 근거 조사 에이전트 → 공식 원문 검색")
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


def main() -> None:
    """Read inputs and display the backend's real decision and approval inbox."""
    st.set_page_config(page_title="적조 안내 갱신 판단", layout="wide")
    st.html("""
        <style>
        [data-testid="stMainBlockContainer"] {padding-top:3.5rem}
        [data-testid="stMainBlockContainer"] h1 {
            font-size:clamp(2rem, 5vw, 3rem);
            word-break:keep-all;
        }
        [data-testid="stMarkdownContainer"] p, .gamak-draft {
            word-break:keep-all;
            overflow-wrap:anywhere;
        }
        .gamak-caption {color:#4A6570;font-size:.875rem;margin:0}
        .gamak-stage {white-space:nowrap}
        </style>
    """)
    st.title("적조 안내 갱신 판단")
    st.html('<p class="gamak-caption">가막만 직전 승인본을 기준시각의 공식 발표와 대조합니다.</p>')

    load_dotenv(Path(os.getenv("GAMAK_ENV_FILE", ".env")))
    mode = os.getenv("GAMAK_MODE", "local").lower()
    ibm_selected = mode in ("watsonx", "watsonx-single")
    db = Path(os.getenv("GAMAK_DB_PATH", "data/local/gamak.sqlite3"))
    default = Request.model_validate_json(REQUEST.read_bytes())
    with st.form("request_form"):
        area, date_column, time_column = st.columns(3)
        region = area.text_input("해역", value=default.region, max_chars=1000)
        day = date_column.date_input("기준 날짜 (KST)", value=default.as_of.date())
        hour = time_column.time_input("기준 시각 (KST)", value=default.as_of.time())
        approved, question_column = st.columns([1, 2])
        notice = approved.text_input("승인된 안내 ID", value=default.approved_notice_id)
        question = question_column.text_input("질문", value=default.question, max_chars=1000)
        submitted = st.form_submit_button("판단 요청", type="primary")

    if submitted:
        st.session_state.fallback = None
        previous = st.session_state.get("collaborative_review")
        st.session_state.collaborative_review = None
        try:
            request = Request(
                region=region, as_of=datetime.combine(day, hour, KST),
                approved_notice_id=NoticeId(notice), question=question,
            )
            st.session_state.review_request = request
            with st.spinner("공식 근거와 승인함을 확인하고 있습니다."):
                try:
                    if mode == "watsonx":
                        outcome = review_collaborative(
                            request, db, previous=previous if isinstance(previous, CollaborativeReview) else None,
                        )
                        st.session_state.result = outcome.result
                        st.session_state.collaborative_review = outcome
                    else:
                        run = review_watsonx if ibm_selected else review
                        st.session_state.result = run(request, db)
                except WatsonxProblem as exc:
                    st.session_state.fallback = str(exc)
                    st.session_state.result = review(request, db)
        except ValidationError:
            st.session_state.result = None
            st.error("해역과 질문을 입력해 주세요.")
        except sqlite3.Error:
            st.session_state.result = None
            st.error("승인함을 열거나 저장할 수 없습니다. DB 경로를 확인해 주세요.")

    result = st.session_state.get("result")
    if not isinstance(result, Result):
        if not submitted:
            wait, inbox = st.columns([2, 1])
            with wait:
                st.info("판단 요청을 누르면 두 경보의 변경 여부를 확인합니다.")
                st.badge("IBM 실호출 대기" if ibm_selected else "로컬 재현", color="gray")
            with inbox:
                try:
                    st.metric("승인 대기 건수", f"{draft_count(db)}건")
                except sqlite3.Error:
                    st.error("승인함을 열 수 없습니다. DB 경로를 확인해 주세요.")
        return

    if fallback := st.session_state.get("fallback"):
        st.warning(f"{fallback} 로컬 자료로 재현했습니다.")
    stored = st.session_state.get("collaborative_review")
    collaborative = stored if isinstance(stored, CollaborativeReview) else None
    if collaborative is not None:
        badge = "IBM 협업 결과 재사용" if collaborative.reused else "IBM 협업 · 원문 검색 확인"
        st.badge(badge, color="green")
    elif result.mode == "watsonx":
        st.badge("IBM 실호출 · 공식 근거 도구 확인", color="green")
    else:
        st.badge("로컬 재현", color="gray")

    request = st.session_state.get("review_request")
    citations = citations_for(request, result, collaborative) if isinstance(request, Request) else {}
    show_workflow(result, collaborative)
    assessment, inbox = st.columns([2, 1])
    with assessment:
        show_assessment(result, citations)
    with inbox:
        show_inbox(result, citations)


main()
