"""The shared request, evidence and response models."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated, Final, Generic, Literal, NewType, TypeVar

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    StringConstraints,
    field_validator,
)

KST: Final = timezone(timedelta(hours=9))
NoticeId = NewType("NoticeId", str)
EvidenceId = NewType("EvidenceId", str)
DraftId = NewType("DraftId", str)
Decision = Literal["갱신 필요", "유지", "확인 필요"]
ExecutionMode = Literal["local", "watsonx"]
LedgerAction = Literal["created", "reused", "checked"]
RegionLevel = Literal["예비특보", "적조주의보", "적조경보", "해제"]
GovernmentLevel = Literal["관심", "주의", "경계", "심각"]
Level = TypeVar("Level", RegionLevel, GovernmentLevel)
NonEmptyText = Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class Request(Contract):
    region: NonEmptyText
    as_of: AwareDatetime
    approved_notice_id: NoticeId
    question: NonEmptyText

    @field_validator("as_of")
    @classmethod
    def use_kst(cls, value: datetime) -> datetime:
        return value.astimezone(KST)


class Evidence(Contract):
    id: EvidenceId
    title: str
    publisher: Literal["해양수산부"]
    published_at: AwareDatetime
    url: str
    summary: str


class Alert(Contract, Generic[Level]):  # noqa: UP046 - shared with the IBM tool runtime
    previous: Level
    current: Level
    effective_at: AwareDatetime
    evidence_id: EvidenceId


class WaterTemperature(Contract):
    status: Literal["확인 필요"] = "확인 필요"
    celsius: None = None


class Assessment(Contract):
    decision: Decision
    reason: str
    regional_alert: Alert[RegionLevel] | None = None
    government_alert: Alert[GovernmentLevel] | None = None
    evidence: tuple[Evidence, ...] = ()
    water_temperature: WaterTemperature = WaterTemperature()
    follow_up_question: str | None = None


class Draft(Contract):
    id: DraftId
    status: Literal["승인 대기"] = "승인 대기"
    text: str


class LedgerStatus(Contract):
    before: int
    after: int
    action: LedgerAction


class Result(Request, Assessment):
    mode: ExecutionMode
    draft: Draft | None
    ledger: LedgerStatus


@dataclass(frozen=True, slots=True)
class PreparedReview:
    request: Request
    assessment: Assessment
    draft: Draft | None
