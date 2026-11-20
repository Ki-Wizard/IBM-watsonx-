"""Read the presentation scenarios and manage separate demo databases."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Final
from uuid import uuid4

from pydantic import ConfigDict

from .contract import KST, Contract, PreparedReview, Request
from .ledger import draft_count
from .service import prepare

EXAMPLES: Final = Path(__file__).resolve().parents[1] / "examples"
CUTOFFS: Final = (datetime(2025, 8, 26, 16, 30, tzinfo=KST), datetime(2025, 8, 29, 16, 30, tzinfo=KST))
_DEMO_ID: Final = re.compile(r"[0-9]{8}-[0-9]{6}-[a-f0-9]{32}")


class Scenario(Contract):
    model_config = ConfigDict(extra="ignore")

    scenario_id: str
    category: str
    request: Request


class ScenarioSet(Contract):
    model_config = ConfigDict(extra="ignore")

    scenarios: tuple[Scenario, ...]


def read_scenarios() -> tuple[Scenario, ...]:
    archived = ScenarioSet.model_validate_json((EXAMPLES / "two-agent-scenarios.json").read_bytes()).scenarios
    return (*archived, Scenario(
        scenario_id="gamak-release", category="가막만 특보 해제 · 9월 26일",
        request=Request.model_validate_json((EXAMPLES / "gamak-release.request.json").read_bytes()),
    ))


def compare_cutoffs(request: Request) -> tuple[PreparedReview, ...]:
    """Apply the same question and approval to both replay cutoffs in memory."""
    return tuple(prepare(request.model_copy(update={"as_of": cutoff})) for cutoff in CUTOFFS)


def _demo_folder(base: Path) -> Path:
    return base.with_name(f"{base.name}-demos")


def demo_ids(base: Path) -> tuple[str, ...]:
    return tuple(sorted(
        (path.stem for path in _demo_folder(base).glob("*.sqlite3")
         if _DEMO_ID.fullmatch(path.stem) and path.is_file() and not path.is_symlink()),
        reverse=True,
    ))


def demo_path(base: Path, demo_id: str) -> Path:
    if demo_id and _DEMO_ID.fullmatch(demo_id):
        return _demo_folder(base) / f"{demo_id}.sqlite3"
    return base


def start_demo(base: Path) -> str:
    """Open a fresh demo database without changing any existing session."""
    demo_id = f"{datetime.now(KST):%Y%m%d-%H%M%S}-{uuid4().hex}"
    draft_count(demo_path(base, demo_id))
    return demo_id
