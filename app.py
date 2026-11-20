"""Streamlit rehearsal screen backed by the real approval inbox."""
from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, time
from pathlib import Path
from typing import Final, assert_never

import streamlit as st
from pydantic import ValidationError

from gamak_demo.contract import (
    KST,
    Alert,
    GovernmentLevel,
    NoticeId,
    RegionLevel,
    Request,
    Result,
)
from gamak_demo.ledger import draft_count
from gamak_demo.service import review

DEFAULT_ID: Final = NoticeId("gamak-2025-08-26-demo")


def _show_alert(label: str, alert: Alert[RegionLevel] | Alert[GovernmentLevel]) -> None:
    with st.container(border=True):
        st.markdown(f"**{label}**")
        st.markdown(f"{alert.previous} → **{alert.current}**")
        if alert.effective_at.tzinfo is not None:
            st.caption(alert.effective_at.astimezone(KST).strftime("%m월 %d일 %H:%M 발령"))


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
            case "checked":
                note = "확인 이력 기록"
            case _ as unreachable:
                assert_never(unreachable)
        st.caption(f"승인함 {ledger.before} → {ledger.after}건 · {note} · 로컬 재현")

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
        st.write(result.draft.text)
        with st.expander("초안 ID"):
            st.code(result.draft.id, language=None, wrap_lines=True)


def main() -> None:
    """Render the demo and process one review on submission."""
    st.set_page_config(page_title="가막만 적조 안내", layout="wide")
    st.title("가막만 적조 안내")
    st.caption("직전 승인본을 기준시각의 공식 발표와 대조합니다.")

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
            try:
                request = Request(
                    region=region, as_of=datetime.combine(day, hour, KST),
                    approved_notice_id=NoticeId(notice), question=question,
                )
                with st.spinner("공식 근거와 승인함을 확인하고 있습니다."):
                    st.session_state.result = review(request, db)
            except ValidationError:
                st.session_state.result = None
                st.error("해역과 질문을 입력해 주세요.")
            except sqlite3.Error:
                st.session_state.result = None
                st.error("승인함을 열거나 저장할 수 없습니다. DB 경로를 확인해 주세요.")

        result = st.session_state.get("result")
        if isinstance(result, Result):
            _show_result(result)
        elif not submitted:
            try:
                st.metric("승인함", f"{draft_count(db)}건")
            except sqlite3.Error:
                st.error("승인함을 열 수 없습니다. DB 경로를 확인해 주세요.")
            st.caption("로컬 재현")


main()
