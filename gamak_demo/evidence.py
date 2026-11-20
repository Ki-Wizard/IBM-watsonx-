"""Look up the archived official announcements known at the replay cutoff."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Generic

from pydantic import AwareDatetime, ValidationError

from .contract import (
    Alert,
    Contract,
    Evidence,
    EvidenceId,
    GovernmentLevel,
    Level,
    NoticeId,
    RegionLevel,
    Request,
    UnconfirmedAlert,
)

ARCHIVE: Final = Path(__file__).resolve().parents[1] / "data" / "gamak-archive.json"
GAMAK: Final = "가막만"
GAMAK_NAMES: Final = frozenset({GAMAK, "여수 가막만", "전남 여수 가막만"})


class IssuedAlert(Contract, Generic[Level]):  # noqa: UP046 - shared with the IBM tool runtime
    value: Level
    effective_at: AwareDatetime


class Announcement(Contract):
    source: Evidence
    regions: tuple[str, ...]
    regional_alert: IssuedAlert[RegionLevel]
    government_alert: IssuedAlert[GovernmentLevel]


class ApprovedNotice(Contract):
    id: NoticeId
    region: str
    approved_at: AwareDatetime
    evidence_ids: tuple[EvidenceId, ...]
    regional_alert: RegionLevel
    regional_effective_at: AwareDatetime
    government_alert: GovernmentLevel
    government_effective_at: AwareDatetime
    text: str


class Archive(Contract):
    documents: tuple[Announcement, ...]
    approved_notices: tuple[ApprovedNotice, ...]


@dataclass(frozen=True, slots=True)
class OfficialReview:
    regional_alert: Alert[RegionLevel]
    government_alert: Alert[GovernmentLevel]
    evidence: tuple[Evidence, ...]
    regional_changed: bool
    government_changed: bool


@dataclass(frozen=True, slots=True)
class UnresolvedReview:
    reason: str
    question: str
    regional_alert: UnconfirmedAlert[RegionLevel] | None = None
    government_alert: UnconfirmedAlert[GovernmentLevel] | None = None
    evidence: tuple[Evidence, ...] = ()


def lookup(request: Request, archive_path: Path) -> OfficialReview | UnresolvedReview:
    """Resolve the approved notice and each alert independently at the requested time."""
    try:
        archive = Archive.model_validate_json(archive_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError):
        return UnresolvedReview(
            "공식 발표 자료를 조회할 수 없습니다.",
            "공식 발표 원문을 확인한 뒤 다시 조회할까요?",
        )

    if request.region not in GAMAK_NAMES:
        return UnresolvedReview(
            "조회 자료에서 요청하신 해역의 특보 적용 범위를 확인할 수 없습니다.",
            "해제 또는 변경 범위를 확인할 해역의 공식 명칭을 알려 주시겠어요?",
        )

    approved = next(
        (notice for notice in archive.approved_notices
         if notice.id == request.approved_notice_id and notice.region == GAMAK
         and notice.approved_at <= request.as_of),
        None,
    )
    if approved is None:
        return UnresolvedReview(
            "기준시각에 유효한 직전 승인본을 찾지 못했습니다.",
            "이 해역의 직전 승인본 ID와 승인 시각을 확인해 주시겠어요?",
        )

    known = tuple(
        item for item in archive.documents
        if GAMAK in item.regions and item.source.published_at <= request.as_of
    )
    sources = {item.source.id: item.source for item in known}
    region = max(
        (item for item in known if item.regional_alert.effective_at <= request.as_of),
        key=lambda item: (item.regional_alert.effective_at, item.source.published_at),
        default=None,
    )
    government = max(
        (item for item in known if item.government_alert.effective_at <= request.as_of),
        key=lambda item: (item.government_alert.effective_at, item.source.published_at),
        default=None,
    )

    if region is None or government is None or not sources.keys() >= set(approved.evidence_ids):
        return UnresolvedReview(
            "기준시각까지 확인 가능한 공식 근거가 부족합니다.",
            "특보와 위기경보 발령 원문을 추가로 확인해 주시겠어요?",
        )

    used = {*approved.evidence_ids, region.source.id, government.source.id}
    evidence = tuple(sorted(
        (sources[key] for key in used),
        key=lambda item: (item.published_at, item.id),
    ))
    if "일부" in request.question and "해제" in request.question and region.regional_alert.value != "해제":
        return UnresolvedReview(
            "조회한 공식 근거로는 일부 해역 해제에 가막만이 포함되는지 확인할 수 없습니다.",
            "국립수산과학원 적조속보에서 해제 대상에 가막만이 포함되는지 확인하시겠어요?",
            regional_alert=UnconfirmedAlert[RegionLevel](
                previous=approved.regional_alert, evidence_id=region.source.id,
            ),
            government_alert=UnconfirmedAlert[GovernmentLevel](
                previous=approved.government_alert, evidence_id=government.source.id,
            ),
            evidence=evidence,
        )

    return OfficialReview(
        regional_alert=Alert[RegionLevel](
            previous=approved.regional_alert, current=region.regional_alert.value,
            effective_at=region.regional_alert.effective_at, evidence_id=region.source.id,
        ),
        government_alert=Alert[GovernmentLevel](
            previous=approved.government_alert, current=government.government_alert.value,
            effective_at=government.government_alert.effective_at, evidence_id=government.source.id,
        ),
        evidence=evidence,
        regional_changed=(
            region.regional_alert.value != approved.regional_alert
            or region.regional_alert.effective_at != approved.regional_effective_at
        ),
        government_changed=(
            government.government_alert.value != approved.government_alert
            or government.government_alert.effective_at != approved.government_effective_at
        ),
    )
