"""Record each review and deduplicate drafts in one SQLite transaction."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Final

from .contract import (
    Draft,
    ExecutionMode,
    LedgerAction,
    LedgerStatus,
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
"""


def draft_count(db: Path) -> int:
    """Return the current approval inbox count, creating the empty schema on first use."""
    db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db)) as connection:
        connection.executescript(_SCHEMA)
        return int(connection.execute("SELECT COUNT(*) FROM drafts").fetchone()[0])


def record(db: Path, prepared: PreparedReview, mode: ExecutionMode) -> Result:
    """Atomically insert or reuse a draft and append the review history."""
    db.parent.mkdir(parents=True, exist_ok=True)
    request, summary, draft = prepared.request, prepared.assessment, prepared.draft
    with closing(sqlite3.connect(db)) as connection, connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(_SCHEMA)
        connection.execute("BEGIN IMMEDIATE")
        before = int(connection.execute("SELECT COUNT(*) FROM drafts").fetchone()[0])
        action: LedgerAction = "checked"
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
        connection.execute(
            "INSERT INTO checks(decision, draft_id, result) VALUES (?, ?, ?)",
            (result.decision, result.draft.id if result.draft else None, result.model_dump_json()),
        )
    return result
