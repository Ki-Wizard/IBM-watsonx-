"""가막만 적조 안내 갱신 판단 — Streamlit 시연 화면."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Final, assert_never

import streamlit as st
from dotenv import load_dotenv
from pydantic import ValidationError

from gamak_demo.contract import (
    KST,
    GovernmentAlert,
    NoticeId,
    RegionalAlert,
    Request,
    Result,
)
from gamak_demo.ledger import draft_count
from gamak_demo.service import review
from gamak_demo.watsonx import WatsonxProblem, review_watsonx

REQUEST: Final = Path(__file__).resolve().parent / "examples" / "gamak-update.request.json"


def show_alert(label: str, alert: RegionalAlert | GovernmentAlert | None) -> None:
    with st.container(border=True):
        if alert is None:
            st.metric(label, "확인 필요")
            return

        st.metric(label, alert.current, f"이전 {alert.previous}", delta_color="off")
        if alert.effective_at is not None:
            issued = alert.effective_at.astimezone(KST).strftime("%m월 %d일 %H:%M 발령")
            st.html(f'<p class="gamak-caption">{issued}</p>')


def show_assessment(result: Result) -> None:
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
        show_alert("해역 적조 특보", result.regional_alert)
    with government:
        show_alert("정부 위기경보", result.government_alert)

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


def show_inbox(result: Result) -> None:
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
        draft_text = escape(result.draft.text)
        if result.government_alert:
            stage = escape(f"‘{result.government_alert.current}’입니다.")
            draft_text = draft_text.replace(stage, f'<span class="gamak-stage">{stage}</span>')
        st.html(f'<p class="gamak-draft">{draft_text}</p>')
        with st.expander("초안 ID"):
            st.code(result.draft.id, language=None, wrap_lines=True)


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
    ibm_selected = os.getenv("GAMAK_MODE", "local").lower() == "watsonx"
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
        try:
            request = Request(
                region=region, as_of=datetime.combine(day, hour, KST),
                approved_notice_id=NoticeId(notice), question=question,
            )
            with st.spinner("공식 근거와 승인함을 확인하고 있습니다."):
                try:
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
    if result.mode == "watsonx":
        st.badge("IBM 실호출 · 공식 근거 도구 확인", color="green")
    else:
        st.badge("로컬 재현", color="gray")

    assessment, inbox = st.columns([2, 1])
    with assessment:
        show_assessment(result)
    with inbox:
        show_inbox(result)


main()
