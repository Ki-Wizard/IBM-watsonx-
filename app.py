"""가막만 적조 안내 갱신 판단 — Streamlit 시연 화면."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from pydantic import SecretStr, ValidationError

from gamak_demo.cloud_store import sync_result_to_cloudant
from gamak_demo.collaborative import CollaborativeReview, review_collaborative
from gamak_demo.contract import Request, Result
from gamak_demo.demo import compare_cutoffs
from gamak_demo.demo_ui import kst_label, request_inputs, select_database, show_comparison
from gamak_demo.evidence import ARCHIVE, GAMAK_NAMES, read_archive
from gamak_demo.hybrid_rag import search_manual
from gamak_demo.ledger import ReviewNote, read_ledger
from gamak_demo.nifs import KEY_ENV, NifsChecked, NifsUnavailable, is_release_question, lookup_release
from gamak_demo.report_ui import (
    citations_for,
    show_ai_governance_and_channels,
    show_assessment,
    show_cloud_sidebar,
    show_notice_comparison,
    show_timeline,
    show_workflow,
)
from gamak_demo.review_ui import show_follow_up, show_inbox, show_ledger_change
from gamak_demo.service import review
from gamak_demo.watsonx import WatsonxProblem, review_watsonx
from gamak_demo.watsonx_ai import evaluate_groundedness, generate_channel_notices


def _run_review(request: Request, db: Path, mode: str, *, note: ReviewNote | None = None) -> bool:
    """Use the configured execution path for both a judgment and a documented retry."""
    previous = st.session_state.get("collaborative_review")
    st.session_state.update(result=None, collaborative_review=None, fallback=None, review_request=None, nifs=None)
    try:
        with st.spinner("공식 근거와 승인함을 확인하고 있습니다."):
            try:
                if mode == "watsonx":
                    outcome = review_collaborative(request, db, previous=previous, note=note)
                    result = outcome.result
                    st.session_state.collaborative_review = outcome
                elif mode == "watsonx-single":
                    result = review_watsonx(request, db, note=note)
                else:
                    key = os.getenv(KEY_ENV, "").strip()
                    report = None
                    if key and request.region in GAMAK_NAMES and is_release_question(request.question):
                        report = lookup_release(SecretStr(key), request)
                    st.session_state.nifs = report
                    result = review(request, db, note=note, nifs=report)
            except WatsonxProblem as exc:
                st.session_state.fallback = str(exc)
                result = review(request, db, note=note)
    except (OSError, sqlite3.Error):
        st.error("승인함을 열거나 저장할 수 없습니다. DB 경로를 확인해 주세요.")
        return False
    st.session_state.update(result=result, review_request=request)
    levels = tuple(
        alert.current
        for alert in (result.regional_alert, result.government_alert)
        if alert is not None and alert.current != "확인 필요"
    )
    manual_hits = search_manual(request.question, levels=levels)
    guidance = manual_hits[0].entry.content if manual_hits else None
    notices = generate_channel_notices(result, manual_guidance=guidance)
    governance = evaluate_groundedness(result, notices)
    cloud_sync = sync_result_to_cloudant(result, note=note, governance=governance)
    st.session_state.update(
        manual_hits=manual_hits,
        channel_notices=notices,
        governance_report=governance,
        cloud_sync=cloud_sync,
    )
    return True


def _result_badge(result: Result, collaboration: CollaborativeReview | None) -> None:
    if fallback := st.session_state.get("fallback"):
        st.warning(f"{fallback} 로컬 자료로 재현했습니다.")
    if collaboration:
        badge = "IBM 협업 결과 재사용" if collaboration.reused else "IBM 협업 · 원문 검색 확인"
        st.badge(badge, color="green")
    elif result.mode == "watsonx":
        st.badge("IBM 실호출 · 공식 근거 도구 확인", color="green")
    else:
        st.badge("로컬 재현", color="gray")
    if is_release_question(result.question):
        nifs = collaboration.collaboration.nifs if collaboration else st.session_state.get("nifs")
        match nifs:
            case NifsChecked():
                st.badge("국립수산과학원 적조속보 조회", color="green")
            case NifsUnavailable():
                st.info("적조속보 API 응답을 확인할 수 없어 보관 자료를 사용했습니다.")
            case None:
                st.badge("적조속보 API 미사용 · 보관 자료", color="gray")


def main() -> None:
    st.set_page_config(page_title="적조 안내 갱신 판단", layout="wide")
    st.html("""
        <style>
        [data-testid="stMainBlockContainer"] {padding-top:3.5rem}
        [data-testid="stMainBlockContainer"] h1 {
            font-size:clamp(2rem, 5vw, 3rem);
            word-break:keep-all;
        }
        [data-testid="stMarkdownContainer"] p, .gamak-draft,
        [data-testid="stText"] span, [data-testid="stCaptionContainer"] p {
            word-break:keep-all;
            overflow-wrap:anywhere;
        }
        [data-testid="stText"] span {
            white-space:pre-wrap;
        }
        .gamak-caption, [data-testid="stCaptionContainer"] p {color:#4A6570;font-size:.875rem}
        .gamak-caption {margin:0}
        [data-testid="stCaptionContainer"] {opacity:1}
        </style>
    """)
    load_dotenv(Path(os.getenv("GAMAK_ENV_FILE", ".env")))
    mode = os.getenv("GAMAK_MODE", "local").lower()
    db = select_database(Path(os.getenv("GAMAK_DB_PATH", "data/local/gamak.sqlite3")).resolve())
    show_cloud_sidebar()
    if db != st.session_state.get("active_db"):
        for key in (
            "result", "collaborative_review", "fallback", "review_request", "comparison", "nifs",
            "manual_hits", "channel_notices", "governance_report", "cloud_sync",
        ):
            st.session_state.pop(key, None)
        st.session_state.active_db = db

    heading, count = st.columns([4, 1], vertical_alignment="center")
    heading.title("적조 안내 갱신 판단")
    heading.html('<p class="gamak-caption">여수 가막만 · 공식 발표와 가상 승인본</p>')
    try:
        archive = read_archive(ARCHIVE)
    except (OSError, UnicodeError, ValidationError):
        st.error("보관 발표와 가상 승인본을 열 수 없습니다.")
        return

    request, submitted, compared = request_inputs(archive)
    if submitted and request:
        st.session_state.pop("comparison", None)
        _run_review(request, db, mode)
    if compared:
        st.session_state.comparison = compare_cutoffs(request) if request else ()
    if comparison := st.session_state.get("comparison"):
        show_comparison(comparison, archive)

    try:
        snapshot = read_ledger(db)
    except (sqlite3.Error, ValidationError):
        st.error("승인함 기록을 읽을 수 없습니다. DB 경로를 확인해 주세요.")
        return
    count.metric("승인 대기 건수", f"{snapshot.pending}건")
    result = st.session_state.get("result")
    reviewed = st.session_state.get("review_request")
    collaboration = st.session_state.get("collaborative_review")
    result_tab, timeline_tab, inbox_tab = st.tabs(
        ["판정 결과", "발표 타임라인", "승인함 · 검토 이력"], key="review_tabs",
    )
    with result_tab:
        if result is None:
            st.info("판단 요청을 누르면 두 경보의 변경 여부를 확인합니다.")
            st.badge("IBM 실호출 대기" if mode.startswith("watsonx") else "로컬 재현", color="gray")
        else:
            _result_badge(result, collaboration)
            st.text(f"{result.region} · 기준 {kst_label(result.as_of)} · {result.question}")
            draft = result.draft
            status = next(
                (item.status for item in snapshot.drafts if draft and item.draft.id == draft.id), "새 초안 없음",
            )
            show_workflow(result, collaboration, status)
            show_ledger_change(result)
            show_assessment(result, citations_for(reviewed, result, collaboration))
            if draft:
                show_notice_comparison(archive, reviewed, result, draft)
            show_ai_governance_and_channels(
                st.session_state.get("channel_notices"),
                st.session_state.get("governance_report"),
                st.session_state.get("manual_hits", ()),
                st.session_state.get("cloud_sync"),
            )
            if (note := show_follow_up(result)) and _run_review(reviewed, db, mode, note=note):
                st.rerun()
    with timeline_tab:
        if request:
            show_timeline(archive, request, result if request == reviewed else None)
        else:
            st.info("해역과 질문을 입력하면 기준시각의 발표 타임라인을 볼 수 있습니다.")
    with inbox_tab:
        show_inbox(db, snapshot)


main()
