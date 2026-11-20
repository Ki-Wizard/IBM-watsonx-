"""Record each review and deduplicate drafts in one SQLite transaction."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, Literal

from .contract import (
    Contract,
    Draft,
    DraftId,
    ExecutionMode,
    LedgerAction,
    LedgerStatus,
    NonEmptyText,
    PreparedReview,
    Result,
)

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS drafts (
    id TEXT PRIMARY KEY,
    body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checks (
    id INTEGER PRIMARY KEY,
    decision TEXT NOT NULL,
    draft_id TEXT REFERENCES drafts (id),
    result TEXT NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS check_notes (
    check_id INTEGER PRIMARY KEY REFERENCES checks (id),
    reviewer TEXT NOT NULL,
    note TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS draft_dispositions (
    draft_id TEXT PRIMARY KEY REFERENCES drafts (id),
    status TEXT NOT NULL CHECK (status IN ('승인', '반려')),
    reviewer TEXT NOT NULL,
    note TEXT NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class ReviewNote(Contract):
    reviewer: NonEmptyText
    note: NonEmptyText


class Disposition(ReviewNote):
    status: Literal["승인", "반려"]


@dataclass(frozen=True, slots=True)
class RecordedDisposition:
    action: Disposition
    at: datetime


@dataclass(frozen=True, slots=True)
class RecordedCheck:
    result: Result
    at: datetime
    note: ReviewNote | None


@dataclass(frozen=True, slots=True)
class InboxEntry:
    draft: Draft
    result: Result
    recorded_at: datetime
    disposition: RecordedDisposition | None

    @property
    def status(self) -> str:
        return self.disposition.action.status if self.disposition else self.draft.status


@dataclass(frozen=True, slots=True)
class LedgerSnapshot:
    drafts: tuple[InboxEntry, ...] = ()
    checks: tuple[RecordedCheck, ...] = ()

    @property
    def pending(self) -> int:
        return sum(entry.disposition is None for entry in self.drafts)


def _utc_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def read_ledger(db: Path) -> LedgerSnapshot:
    """Read one SQLite snapshot, including databases from before review notes existed."""
    if not db.exists():
        return LedgerSnapshot()
    with closing(sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        connection.execute("BEGIN")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "checks" not in tables:
            return LedgerSnapshot()
        query = "SELECT result, recorded_at, NULL, NULL FROM checks ORDER BY id DESC"
        if "check_notes" in tables:
            query = """
                SELECT c.result, c.recorded_at, n.reviewer, n.note
                FROM checks c LEFT JOIN check_notes n ON n.check_id = c.id
                ORDER BY c.id DESC
            """
        checks = tuple(
            RecordedCheck(
                Result.model_validate_json(payload), _utc_timestamp(at),
                ReviewNote(reviewer=reviewer, note=note) if reviewer is not None else None,
            )
            for payload, at, reviewer, note in connection.execute(query)
        )
        dispositions = {}
        if "draft_dispositions" in tables:
            dispositions = {
                draft_id: RecordedDisposition(Disposition(status=status, reviewer=reviewer, note=note), _utc_timestamp(at))
                for draft_id, status, reviewer, note, at in connection.execute(
                    "SELECT draft_id, status, reviewer, note, recorded_at FROM draft_dispositions"
                )
            }

    entries: dict[DraftId, InboxEntry] = {}
    for check in reversed(checks):
        if (draft := check.result.draft) is not None and draft.id not in entries:
            entries[draft.id] = InboxEntry(draft, check.result, check.at, dispositions.get(draft.id))
    return LedgerSnapshot(tuple(reversed(entries.values())), checks)


def set_disposition(db: Path, draft_id: DraftId, action: Disposition) -> bool:
    """Record one terminal decision per existing draft, even across concurrent reviewers."""
    with closing(sqlite3.connect(db)) as connection, connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(_SCHEMA)
        inserted = connection.execute(
            """
            INSERT INTO draft_dispositions(draft_id, status, reviewer, note)
            SELECT id, ?, ?, ? FROM drafts WHERE id = ? ON CONFLICT(draft_id) DO NOTHING
            """,
            (action.status, action.reviewer, action.note, draft_id),
        ).rowcount
    return inserted == 1


def draft_count(db: Path) -> int:
    """Return the current approval inbox count, creating the empty schema on first use."""
    db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db)) as connection:
        connection.executescript(_SCHEMA)
        return int(connection.execute("SELECT COUNT(*) FROM drafts").fetchone()[0])


def record(
    db: Path, prepared: PreparedReview, mode: ExecutionMode, *, note: ReviewNote | None = None,
) -> Result:
    """Atomically insert or reuse a draft and append the review history."""
    db.parent.mkdir(parents=True, exist_ok=True)
    request, summary, draft = prepared.request, prepared.assessment, prepared.draft
    with closing(sqlite3.connect(db)) as connection, connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(_SCHEMA)
        connection.execute("BEGIN IMMEDIATE")
        before = int(connection.execute("SELECT COUNT(*) FROM drafts").fetchone()[0])
        action: LedgerAction = "none"
        if draft is not None:
            inserted = connection.execute(
                "INSERT INTO drafts(id, body) VALUES (?, ?) ON CONFLICT(id) DO NOTHING",
                (draft.id, draft.model_dump_json()),
            ).rowcount
            action = "created" if inserted else "reused"
            if not inserted:
                row = connection.execute("SELECT body FROM drafts WHERE id = ?", (draft.id,)).fetchone()
                draft = Draft.model_validate_json(row[0])

        result = Result(
            region=request.region, as_of=request.as_of, question=request.question,
            approved_notice_id=request.approved_notice_id, decision=summary.decision,
            reason=summary.reason, regional_alert=summary.regional_alert,
            government_alert=summary.government_alert, evidence=summary.evidence,
            water_temperature=summary.water_temperature, follow_up_question=summary.follow_up_question,
            mode=mode, draft=draft,
            ledger=LedgerStatus(before=before, after=before + int(action == "created"), action=action),
        )
        check = connection.execute(
            "INSERT INTO checks(decision, draft_id, result) VALUES (?, ?, ?)",
            (result.decision, result.draft.id if result.draft else None, result.model_dump_json()),
        )
        if note is not None:
            connection.execute(
                "INSERT INTO check_notes(check_id, reviewer, note) VALUES (?, ?, ?)",
                (check.lastrowid, note.reviewer, note.note),
            )
    return result
