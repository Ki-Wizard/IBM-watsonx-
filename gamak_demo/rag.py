"""Retrieve dated excerpts from the public rehearsal archive for the researcher."""
from __future__ import annotations

from pathlib import Path
from typing import Literal, NewType

from pydantic import AwareDatetime, ValidationError

from .contract import Contract, EvidenceId, GovernmentLevel, RegionLevel, Request
from .evidence import (
    ARCHIVE,
    GAMAK_NAMES,
    Announcement,
    Excerpt,
    PassageTopic,
    current_announcements,
    find_approval,
    known_announcements,
    read_archive,
)

PassageId = NewType("PassageId", str)
RetrievalStatus = Literal["available", "unknown_region", "missing_approval", "unavailable"]


class ApprovedLevels(Contract):
    regional: RegionLevel
    government: GovernmentLevel
    regional_effective_at: AwareDatetime
    government_effective_at: AwareDatetime


class Passage(Excerpt):
    id: PassageId
    source_id: EvidenceId
    published_at: AwareDatetime
    level: RegionLevel | GovernmentLevel | None = None
    effective_at: AwareDatetime | None = None


class Retrieval(Contract):
    status: RetrievalStatus
    approved: ApprovedLevels | None = None
    passages: tuple[Passage, ...] = ()


def retrieve(request: Request, archive_path: Path = ARCHIVE) -> Retrieval:
    """Return source excerpts plus the comparison baseline, without a verdict."""
    if request.region not in GAMAK_NAMES:
        return Retrieval(status="unknown_region")
    try:
        archive = read_archive(archive_path)
    except (OSError, UnicodeError, ValidationError):
        return Retrieval(status="unavailable")
    approved = find_approval(archive, request)
    if approved is None:
        return Retrieval(status="missing_approval")

    include_water = any(term in request.question for term in ("수온", "물 온도", "℃"))
    known = known_announcements(archive, request)
    regional, government = current_announcements(known, request.as_of)
    targets: list[tuple[PassageTopic, Announcement | None]] = [
        ("regional", regional), ("government", government),
    ]
    if include_water:
        targets.append(("water_background", max(
            (row for row in known if any(item.topic == "water_background" for item in row.passages)),
            key=lambda row: row.source.published_at, default=None,
        )))
    passages: list[Passage] = []
    for topic, row in targets:
        if row is None:
            continue
        excerpt = next((item for item in row.passages if item.topic == topic), None)
        if excerpt is None:
            continue
        match topic:
            case "regional":
                level, effective_at = row.regional_alert.value, row.regional_alert.effective_at
            case "government":
                level, effective_at = row.government_alert.value, row.government_alert.effective_at
            case "water_background":
                level, effective_at = None, None
        passages.append(Passage(
            id=PassageId(f"{row.source.id}-{topic}"), source_id=row.source.id,
            published_at=row.source.published_at, topic=topic,
            location=excerpt.location, text=excerpt.text, level=level, effective_at=effective_at,
        ))
    return Retrieval(
        status="available" if passages else "unavailable",
        approved=ApprovedLevels(
            regional=approved.regional_alert, government=approved.government_alert,
            regional_effective_at=approved.regional_effective_at,
            government_effective_at=approved.government_effective_at,
        ),
        passages=tuple(passages),
    )
