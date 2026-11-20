"""Streamlit controls for presentation scenarios, cutoffs, and sessions."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import streamlit as st
from pydantic import ValidationError

from .contract import KST, NoticeId, PreparedReview, Request
from .demo import EXAMPLES, Scenario, demo_ids, demo_path, read_scenarios, start_demo
from .evidence import ApprovedNotice, Archive


def kst_label(at: datetime) -> str:
    return at.astimezone(KST).strftime("%Y-%m-%d %H:%M KST")


def _session_label(demo_id: str) -> str:
    if not demo_id:
        return "리허설 DB"
    created = datetime.strptime(demo_id[:15], "%Y%m%d-%H%M%S").replace(tzinfo=KST)
    return f"데모 · {kst_label(created)} · {demo_id[16:22]}"


def _set_demo(demo_id: str) -> None:
    if demo_id:
        st.query_params["demo"] = demo_id
    else:
        st.query_params.pop("demo", None)


def _new_demo(base: Path) -> None:
    try:
        demo_id = start_demo(base)
    except (OSError, sqlite3.Error):
        st.session_state.demo_error = "새 데모 DB를 열 수 없습니다. 저장 경로를 확인해 주세요."
    else:
        _set_demo(demo_id)


def select_database(base: Path) -> Path:
    """Resolve a saved session ID from the sidebar and browser URL."""
    options = ("", *demo_ids(base))
    active = st.query_params.get("demo", "")
    if active not in options:
        active = ""
        _set_demo(active)
    st.session_state.demo_session = active
    with st.sidebar:
        st.header("데모 세션")
        st.selectbox(
            "열린 승인함", options, format_func=_session_label, key="demo_session",
            on_change=lambda: _set_demo(st.session_state.demo_session),
        )
        st.button("새 데모 시작", key="new_demo", on_click=_new_demo, args=(base,))
        if message := st.session_state.pop("demo_error", None):
            st.error(message)
    return demo_path(base, active)


def _fill_request(request: Request) -> None:
    st.session_state.update(
        region=request.region, as_of_day=request.as_of.date(), as_of_time=request.as_of.time(),
        notice=request.approved_notice_id, question=request.question,
    )


def _load_scenario(scenarios: dict[str, Scenario]) -> None:
    _fill_request(scenarios[st.session_state.scenario].request)


def request_inputs(archive: Archive) -> tuple[Request | None, bool, bool]:
    """Edit or load a request and report which explicit action was taken."""
    if "region" not in st.session_state:
        _fill_request(Request.model_validate_json((EXAMPLES / "gamak-update.request.json").read_bytes()))

    scenarios = {entry.scenario_id: entry for entry in read_scenarios()}
    chooser, loader = st.columns([3, 1], vertical_alignment="bottom")
    scenario = chooser.selectbox(
        "예시 질문", tuple(scenarios), index=tuple(scenarios).index("cutoff-compare-update"),
        format_func=lambda key: scenarios[key].category, key="scenario",
    )
    loader.button("예시 불러오기", key="load_scenario", on_click=_load_scenario, args=(scenarios,))
    if scenario == "repeat-idempotency":
        st.info("먼저 시점 B(8월 29일) 예시를 불러와 판단을 요청하세요. 이후 같은 요청을 한 번 더 제출하세요.")

    with st.container(border=True):
        area, date_column, time_column = st.columns(3)
        region = area.text_input("해역", key="region", max_chars=1000)
        day = date_column.date_input("기준 날짜 (KST)", key="as_of_day")
        hour = time_column.time_input("기준 시각 (KST)", key="as_of_time", step=60)
        notices = {notice.id: notice for notice in archive.approved_notices}
        notice_id = st.selectbox(
            "과거 승인본", tuple(notices), key="notice",
            format_func=lambda key: f"{notices[key].approved_at:%m월 %d일} · {notices[key].region} 가상 승인본",
        )
        show_notice(notices[notice_id])
        question = st.text_area("질문", key="question", height="content", max_chars=1000)
        judge, compare = st.columns(2)
        submitted = judge.button("판단 요청", type="primary", key="judge", width="stretch")
        compared = compare.button("두 기준시각 비교", key="compare", width="stretch")

    try:
        request = Request(
            region=region, as_of=datetime.combine(day, hour, KST),
            approved_notice_id=NoticeId(notice_id), question=question,
        )
    except ValidationError:
        if submitted or compared:
            st.error("해역과 질문을 입력해 주세요.")
        return None, submitted, compared
    return request, submitted, compared


def show_notice(notice: ApprovedNotice) -> None:
    with st.expander("과거 승인본 미리보기"):
        st.caption(f"승인 시각 {kst_label(notice.approved_at)}")
        st.markdown(f"**해역 적조 특보** {notice.regional_alert} · **정부 위기경보** {notice.government_alert}")
        st.write(notice.text)


def show_comparison(reviews: tuple[PreparedReview, ...], archive: Archive) -> None:
    st.subheader("두 기준시각 비교")
    request = reviews[0].request
    notice = next(item for item in archive.approved_notices if item.id == request.approved_notice_id)
    st.caption(f"조회 전용 · {notice.approved_at:%m월 %d일} 가상 승인본")
    st.text(f"{request.region} · {request.question}")
    earlier = {source.id for source in reviews[0].assessment.evidence}
    for index, (column, review) in enumerate(zip(st.columns(2), reviews, strict=True)):
        result = review.assessment
        with column, st.container(border=True):
            st.caption(kst_label(review.request.as_of))
            st.subheader(result.decision)
            st.write(result.reason)
            regional, government = result.regional_alert, result.government_alert
            st.markdown(f"**해역 적조 특보** · {regional.current if regional else '확인 필요'}")
            st.markdown(f"**정부 위기경보** · {government.current if government else '확인 필요'}")
            st.markdown("**추가로 조회된 공식 발표**" if index else "**조회된 공식 발표**")
            sources = [source for source in result.evidence if not index or source.id not in earlier]
            if not sources:
                st.caption("해당 발표 없음")
            for source in sources:
                st.markdown(f"[{source.title}]({source.url})")
    st.button("비교 닫기", on_click=st.session_state.pop, args=("comparison", None))
