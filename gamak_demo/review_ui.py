"""Streamlit views for follow-up checks and the SQLite approval inbox."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Final

import streamlit as st
from pydantic import ValidationError

from .contract import Result
from .demo_ui import kst_label
from .ledger import Disposition, InboxEntry, LedgerSnapshot, RecordedCheck, ReviewNote, set_disposition

ACTION_LABELS: Final = {
    "created": "초안 1건 등록", "reused": "기존 초안 재사용", "none": "확인 이력 기록",
}
RED_TIDE_BULLETINS: Final = "https://www.nifs.go.kr/board/actionRedtideInfoList.do"
WATER_OBSERVATIONS: Final = "https://www.nifs.go.kr/gis/femo_new/map.jsp"


def show_follow_up(result: Result) -> ReviewNote | None:
    """Collect a note for a new check of the same decision inputs."""
    water_needed = result.draft is not None or any(term in result.question for term in ("수온", "물 온도", "℃"))
    if not (result.follow_up_question or water_needed):
        return None
    st.subheader("확인 필요 후속 작업")
    if result.follow_up_question:
        with st.container(border=True):
            release_needed = any(phrase in result.follow_up_question for phrase in ("해제 대상", "해제 범위"))
            item = "해제 범위" if release_needed else "해역·승인본 또는 공식 근거"
            st.markdown(f"**{item} · 확인 필요**")
            st.write(result.follow_up_question)
            st.markdown(f"[국립수산과학원 적조속보]({RED_TIDE_BULLETINS})")
    if water_needed:
        with st.container(border=True):
            st.markdown("**실측 수온 · 확인 필요**")
            st.write("기준시각의 가막만 관측값을 어느 정점과 수심에서 확인할 수 있나요?")
            st.markdown(f"[국립수산과학원 어장환경 관측자료]({WATER_OBSERVATIONS})")
    with st.form("follow_up", clear_on_submit=True):
        st.caption("같은 요청을 공식 근거로 다시 판단하고 확인 메모를 검토 이력에 남깁니다.")
        reviewer = st.text_input("확인 담당자", max_chars=100)
        content = st.text_area("확인 메모", max_chars=1000)
        if st.form_submit_button("메모 저장 및 재판단", key="retry"):
            try:
                return ReviewNote(reviewer=reviewer, note=content)
            except ValidationError:
                st.error("확인 담당자와 확인 메모를 입력해 주세요.")
    return None


def show_ledger_change(result: Result) -> None:
    ledger = result.ledger
    st.markdown(f"**승인함 {ledger.before} → {ledger.after}건** · {ACTION_LABELS[ledger.action]}")


def _show_check(check: RecordedCheck) -> None:
    result = check.result
    st.markdown(f"**{result.decision}** · {ACTION_LABELS[result.ledger.action]}")
    st.caption(f"처리 {kst_label(check.at)} · 기준 {kst_label(result.as_of)}")
    st.text(result.question)
    if result.follow_up_question:
        st.write(result.follow_up_question)
    if check.note:
        st.caption(f"확인 담당자 · {check.note.reviewer}")
        st.text(check.note.note)


def _show_draft(db: Path, entry: InboxEntry, snapshot: LedgerSnapshot) -> None:
    result = entry.result
    st.markdown(f"**{entry.status}** · 최초 판정 **{result.decision}**")
    st.caption(
        f"{result.region} · 등록 {kst_label(entry.recorded_at)}  \n판정 기준 {kst_label(result.as_of)}",
    )
    st.write(result.reason)
    st.write(entry.draft.text)
    for source in result.evidence:
        st.markdown(f"[{source.title}]({source.url})")
    with st.expander("초안 ID"):
        st.code(entry.draft.id, language=None, wrap_lines=True)
    if disposition := entry.disposition:
        with st.container(border=True):
            st.markdown(f"**{disposition.action.status}** · {disposition.action.reviewer}")
            st.caption(f"처리 {kst_label(disposition.at)}")
            st.text(disposition.action.note)
    else:
        _disposition_form(db, entry)
    with st.expander("이 초안의 판정 및 재사용 이력"):
        for check in snapshot.checks:
            if check.result.draft and check.result.draft.id == entry.draft.id:
                with st.container(border=True):
                    _show_check(check)


def _disposition_form(db: Path, entry: InboxEntry) -> None:
    with st.form(f"disposition-{entry.draft.id}"):
        reviewer = st.text_input("처리 담당자", max_chars=100)
        memo = st.text_area("처리 메모", max_chars=1000)
        approve, reject = st.columns(2)
        approved = approve.form_submit_button("승인", type="primary", width="stretch", key="approve")
        rejected = reject.form_submit_button("반려", width="stretch", key="reject")
        if not (approved or rejected):
            return
        try:
            action = Disposition(status="승인" if approved else "반려", reviewer=reviewer, note=memo)
            saved = set_disposition(db, entry.draft.id, action)
        except ValidationError:
            st.error("처리 담당자와 처리 메모를 입력해 주세요.")
        except sqlite3.Error:
            st.error("처리 결과를 저장할 수 없습니다.")
        else:
            st.session_state.inbox_message = (
                f"초안의 {action.status} 기록을 저장했습니다." if saved else "이미 처리된 초안입니다."
            )
            st.rerun()


def show_inbox(db: Path, snapshot: LedgerSnapshot) -> None:
    st.subheader("승인함")
    st.caption(f"전체 {len(snapshot.drafts)}건 · 승인 대기 {snapshot.pending}건")
    if message := st.session_state.pop("inbox_message", None):
        st.info(message)
    if not snapshot.drafts:
        st.info("이 세션에 등록된 초안이 없습니다.")
    else:
        entries = {entry.draft.id: entry for entry in snapshot.drafts}
        selected = st.selectbox(
            "검토할 초안", tuple(entries), key=f"inbox-{db.name}",
            format_func=lambda key: (
                f"{entries[key].status} · 기준 {kst_label(entries[key].result.as_of)} · {key[6:14]}"
            ),
        )
        _show_draft(db, entries[selected], snapshot)
    with st.expander("전체 검토 이력"):
        if not snapshot.checks:
            st.caption("아직 기록된 판단 요청이 없습니다.")
        for check in snapshot.checks:
            with st.container(border=True):
                _show_check(check)
