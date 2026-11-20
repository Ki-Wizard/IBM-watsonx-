"""가막만 적조 안내 갱신 판단 — 데모 화면

연동 전에는 examples/ 의 공통 예시 JSON을 읽어 표시한다.
실행: streamlit run app.py
"""

import json
from datetime import datetime
from pathlib import Path

import streamlit as st

EXAMPLES = Path(__file__).parent / "examples"
REQUEST_FILE = EXAMPLES / "gamak-update.request.json"
EXPECTED_FILE = EXAMPLES / "gamak-update.expected.json"

DECISION_STYLE = {
    "갱신 필요": st.error,
    "유지": st.success,
    "확인 필요": st.warning,
}


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def fmt_time(iso: str | None) -> str:
    if not iso:
        return "-"
    return datetime.fromisoformat(iso).strftime("%m월 %d일 %H:%M")


def get_result(request: dict) -> dict:
    # TODO: 백엔드 연동 시 이 함수만 실제 호출로 교체
    return load_json(EXPECTED_FILE)


def show_alert(col, label: str, alert: dict, evidence_by_id: dict) -> None:
    col.metric(label, alert["current"], f"이전: {alert['previous']}", delta_color="off")
    col.caption(f"적용 시각 {fmt_time(alert.get('effective_at'))}")
    ev = evidence_by_id.get(alert.get("evidence_id"))
    if ev:
        col.markdown(f"근거: [{ev['title']}]({ev['url']})")


st.set_page_config(page_title="적조 안내 갱신 판단", layout="wide")
st.title("적조 안내 갱신 판단")

default_req = load_json(REQUEST_FILE)
default_time = datetime.fromisoformat(default_req["as_of"])

# ── 입력 ──────────────────────────────────────────
with st.form("request_form"):
    c1, c2, c3 = st.columns(3)
    region = c1.text_input("해역", value=default_req["region"])
    date = c2.date_input("기준 날짜 (KST)", value=default_time.date())
    time = c3.time_input("기준 시각 (KST)", value=default_time.time().replace(tzinfo=None))
    notice_id = st.text_input("승인된 안내 ID", value=default_req["approved_notice_id"])
    question = st.text_input("질문", value=default_req["question"])
    submitted = st.form_submit_button("판단 요청", type="primary")

if submitted:
    as_of = datetime.combine(date, time, tzinfo=default_time.tzinfo).isoformat()
    request = {
        "region": region,
        "as_of": as_of,
        "approved_notice_id": notice_id,
        "question": question,
    }
    st.session_state.result = get_result(request)

result = st.session_state.get("result")

if result is None:
    st.info("'판단 요청'을 누르면 결과가 표시됩니다.")
    st.stop()

evidence_by_id = {ev["id"]: ev for ev in result.get("evidence", [])}
st.caption(f"실행 모드: {result.get('mode', '-')}")

left, right = st.columns([2, 1])

# ── 판정과 두 경보 ─────────────────────────────────
with left:
    st.subheader("판정")
    DECISION_STYLE.get(result["decision"], st.info)(f"**{result['decision']}** — {result['reason']}")

    a1, a2 = st.columns(2)
    show_alert(a1, "해역 적조 특보", result["regional_alert"], evidence_by_id)
    show_alert(a2, "정부 위기경보", result["government_alert"], evidence_by_id)

    temp = result.get("water_temperature") or {}
    if temp.get("celsius") is not None:
        st.write(f"수온: {temp['celsius']}℃")
    else:
        st.warning(f"수온: {temp.get('status', '확인 필요')}")

    if result.get("follow_up_question"):
        st.warning(f"확인 질문: {result['follow_up_question']}")

    st.subheader("공식 원문")
    for ev in result.get("evidence", []):
        st.markdown(
            f"- [{ev['title']}]({ev['url']}) · {ev['publisher']} · {fmt_time(ev['published_at'])}  \n"
            f"  {ev['summary']}"
        )

# ── 초안과 승인함 ─────────────────────────────────
with right:
    st.subheader("승인함")
    ledger = result.get("ledger") or {}
    st.metric(
        "승인 대기 건수",
        f"{ledger.get('after', 0)}건",
        f"{ledger.get('before', 0)} → {ledger.get('after', 0)} ({ledger.get('action', '-')})",
        delta_color="off",
    )

    draft = result.get("draft")
    if draft:
        st.subheader("초안")
        st.write(f"상태: {draft['status']}")
        st.info(draft["text"])
        st.caption(f"초안 ID: {draft['id'][:20]}…")
