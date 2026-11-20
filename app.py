"""Streamlit rehearsal screen backed by the real approval inbox."""
from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, time
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

DEFAULT_ID: Final = NoticeId("gamak-2025-08-26-demo")


def _show_alert(label: str, alert: RegionalAlert | GovernmentAlert) -> None:
    with st.container(border=True):
        st.markdown(f"**{label}**")
        st.markdown(f"{alert.previous} → **{alert.current}**")
        if alert.effective_at is not None:
            issued = alert.effective_at.astimezone(KST).strftime("%m월 %d일 %H:%M 발령")
            st.html(f'<p class="gamak-caption">{issued}</p>')


def _show_result(result: Result) -> None:
    with st.container(border=True):
        st.subheader(result.decision)
        st.write(result.reason)
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
        st.markdown(f"**승인함 {ledger.before} → {ledger.after}건** · {note}")
        if result.mode == "watsonx":
            st.badge("IBM 실호출 · 공식 근거 도구 확인", color="green")
        else:
            st.badge("로컬 재현", color="gray")

    if result.regional_alert and result.government_alert:
        regional, government = st.columns(2)
        with regional:
            _show_alert("해역 특보", result.regional_alert)
        with government:
            _show_alert("정부 위기경보", result.government_alert)

    if result.evidence:
        st.subheader("공식 근거")
        for source in result.evidence:
            st.markdown(f"[해양수산부 · {source.title}]({source.url})")

    if result.follow_up_question:
        st.warning(result.follow_up_question)

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
    """Render the demo and process one review on submission."""
    st.set_page_config(page_title="가막만 적조 안내", layout="wide")
    st.html("""
        <style>
        [data-testid="stMainBlockContainer"] {padding-top:3.5rem}
        [data-testid="stMarkdownContainer"] p, .gamak-draft {
            word-break:keep-all;
            overflow-wrap:anywhere;
        }
        .gamak-caption {color:#4A6570;font-size:.875rem;margin:0}
        .gamak-stage {white-space:nowrap}
        </style>
    """)
    st.title("가막만 적조 안내")
    st.html('<p class="gamak-caption">직전 승인본을 기준시각의 공식 발표와 대조합니다.</p>')

    load_dotenv(Path(os.getenv("GAMAK_ENV_FILE", ".env")))
    ibm_selected = os.getenv("GAMAK_MODE", "local").lower() == "watsonx"
    db = Path(os.getenv("GAMAK_DB_PATH", "data/local/gamak.sqlite3"))
    inputs, output = st.columns([1, 1.45], gap="large")
    with inputs:
        st.subheader("안내 확인")
        with st.form("review"):
            region = st.text_input("해역", "가막만", max_chars=1000)
            day = st.date_input("기준 날짜 (KST)", date(2025, 8, 29))
            hour = st.time_input("기준 시각 (KST)", time(16, 30))
            notice = st.text_input("직전 승인본 ID", DEFAULT_ID)
            question = st.text_area("질문", "이 안내를 계속 써도 되나?", max_chars=1000)
            submitted = st.form_submit_button("안내 확인하기", type="primary", width="stretch")

    with output:
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
        if isinstance(result, Result):
            if fallback := st.session_state.get("fallback"):
                st.warning(f"{fallback} 로컬 자료로 재현했습니다.")
            _show_result(result)
        elif not submitted:
            try:
                st.metric("승인함", f"{draft_count(db)}건")
            except sqlite3.Error:
                st.error("승인함을 열 수 없습니다. DB 경로를 확인해 주세요.")
            st.caption("IBM 실호출 대기" if ibm_selected else "로컬 재현")


main()
