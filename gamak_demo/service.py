"""Apply the demo decision rules and send the result through the ledger."""
from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import assert_never

from .contract import (
    Alert,
    Assessment,
    Draft,
    DraftId,
    Evidence,
    EvidenceId,
    ExecutionMode,
    GovernmentLevel,
    PreparedReview,
    RegionLevel,
    Request,
    Result,
)
from .evidence import ARCHIVE, GAMAK, OfficialReview, UnresolvedReview, lookup
from .ledger import ReviewNote, record
from .nifs import NifsChecked, NifsReport, is_release_question, release_excerpt
from .rag import retrieve


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


def _prepare_archive(request: Request, archive: Path) -> PreparedReview:
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


def prepare(
    request: Request, archive: Path = ARCHIVE, *, nifs: NifsReport | None = None,
) -> PreparedReview:
    """Determine the response from one cutoff and the available official sources."""
    prepared = _prepare_archive(request, archive)
    if isinstance(nifs, NifsChecked) and is_release_question(request.question):
        return _with_release_evidence(prepared, archive, nifs)
    return prepared


def _with_release_evidence(prepared: PreparedReview, archive: Path, report: NifsChecked) -> PreparedReview:
    request, original = prepared.request, prepared.assessment
    retrieval = retrieve(request, archive)
    approved = retrieval.approved
    passage = next((item for item in retrieval.passages if item.topic == "government"), None)
    if approved is None or passage is None or passage.source_id not in {item.id for item in original.evidence}:
        return prepared

    government = Alert[GovernmentLevel].model_validate({
        "previous": approved.government, "current": passage.level,
        "effective_at": passage.effective_at, "evidence_id": passage.source_id,
    })
    bulletin = report.bulletin
    excerpt = release_excerpt(bulletin, request) if bulletin else None
    if bulletin is None or excerpt is None or bulletin.known_by is None:
        return PreparedReview(request, Assessment(
            decision="확인 필요",
            reason="적조속보에서 가막만 해제 범위 또는 기준시각의 공개 여부를 확인할 수 없습니다.",
            government_alert=government, evidence=original.evidence,
            follow_up_question="국립수산과학원 적조속보에서 가막만의 해제 범위와 공개 시각을 확인하시겠어요?",
        ), None)

    source = Evidence(
        id=EvidenceId(f"nifs-{bulletin.code}"), title=f"적조속보 {bulletin.survey_day:%Y.%m.%d}",
        publisher="국립수산과학원", published_at=bulletin.known_by,
        url=bulletin.url, summary=excerpt,
    )
    regional = Alert[RegionLevel](
        previous=approved.regional, current="해제", effective_at=None, evidence_id=source.id,
    )
    return _assess(request, OfficialReview(
        regional_alert=regional, government_alert=government, evidence=(*original.evidence, source),
        regional_changed=approved.regional != "해제",
        government_changed=(
            approved.government != government.current or approved.government_effective_at != government.effective_at
        ),
    ))


def finalize(
    prepared: PreparedReview, db: Path, mode: ExecutionMode, *, note: ReviewNote | None = None,
) -> Result:
    """Commit the prepared result and return the authoritative ledger state."""
    return record(db, prepared, mode, note=note)


def review(
    request: Request, db: Path, *, archive: Path = ARCHIVE,
    note: ReviewNote | None = None, nifs: NifsReport | None = None,
) -> Result:
    """Check the official evidence and persist a local review."""
    return finalize(prepare(request, archive, nifs=nifs), db, "local", note=note)
