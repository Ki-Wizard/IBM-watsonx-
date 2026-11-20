"""Apply the demo decision rules and send the result through the ledger."""
from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import assert_never

from .contract import (
    Assessment,
    Draft,
    DraftId,
    ExecutionMode,
    PreparedReview,
    Request,
    Result,
)
from .evidence import ARCHIVE, GAMAK, OfficialReview, UnresolvedReview, lookup
from .ledger import record


def _time(at: datetime) -> str:
    return f"{at.hour}시" + (f" {at.minute}분" if at.minute else "")


def _assess(request: Request, official: OfficialReview) -> PreparedReview:
    regional = official.regional_alert
    government = official.government_alert
    changes = [
        label for label, changed in (
            ("해역 특보", official.regional_changed),
            ("정부 위기경보", official.government_changed),
        ) if changed
    ]
    reason = "직전 승인본 이후 해역 특보와 정부 위기경보의 변경이 확인되지 않았습니다."
    if changes:
        reason = (
            "직전 승인본과 비교해 해역 특보와 정부 위기경보가 모두 변경됐습니다."
            if len(changes) == 2 else f"변경된 항목은 {changes[0]}입니다."
        )
    summary = Assessment(
        decision="갱신 필요" if changes else "유지", reason=reason,
        regional_alert=regional, government_alert=government, evidence=official.evidence,
    )
    if not changes:
        return PreparedReview(request, summary, None)

    seed = json.dumps(
        (GAMAK, request.approved_notice_id, *(source.id for source in official.evidence)),
        ensure_ascii=False, separators=(",", ":"),
    )
    at = regional.effective_at
    gov_at = government.effective_at
    if regional.current == "해제":
        regional_phrase = "해제됐습니다."
    elif regional.previous != regional.current:
        regional_phrase = f"{regional.current}로 변경됐습니다."
    else:
        regional_phrase = f"{regional.current}입니다."
    when = f"{at.month}월 {at.day}일 {_time(at)}부터" if at else "공식 발표에 따르면"
    if gov_at is None:
        government_when = "공식 발표에 따르면"
    else:
        gov_date = "같은 날" if at and at.date() == gov_at.date() else f"{gov_at.month}월 {gov_at.day}일"
        government_when = f"{gov_date} {_time(gov_at)}부터"
    return PreparedReview(request, summary, Draft(
        id=DraftId(f"draft-{sha256(seed.encode('utf-8')).hexdigest()}"),
        text=(
            f"{GAMAK} 적조 특보는 {when} {regional_phrase} "
            f"정부 위기경보는 {government_when} ‘{government.current}’입니다. "
            f"당시 {GAMAK} 수온은 확인이 필요합니다."
        ),
    ))


def prepare(request: Request, archive: Path = ARCHIVE) -> PreparedReview:
    """Determine the proposed response without creating a draft or check history."""
    match lookup(request, archive):
        case OfficialReview() as official:
            return _assess(request, official)
        case UnresolvedReview() as unresolved:
            return PreparedReview(
                request, Assessment(
                    decision="확인 필요", reason=unresolved.reason, follow_up_question=unresolved.question,
                    regional_alert=unresolved.regional_alert, government_alert=unresolved.government_alert,
                    evidence=unresolved.evidence,
                ),
                None,
            )
        case _ as unreachable:
            assert_never(unreachable)


def finalize(prepared: PreparedReview, db: Path, mode: ExecutionMode) -> Result:
    """Commit the prepared result and return the authoritative ledger state."""
    return record(db, prepared, mode)


def review(request: Request, db: Path, *, archive: Path = ARCHIVE) -> Result:
    """Check the official evidence and persist a local review."""
    return finalize(prepare(request, archive), db, "local")
