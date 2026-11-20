"""Typed messages shared by the Orchestrate evidence tool and validation client."""
from __future__ import annotations

from hashlib import sha256
from typing import Final

from .contract import Contract, Decision
from .nifs import NifsReport
from .rag import PassageId, Retrieval

SUPERVISOR: Final = "kiw_gamak_supervisor"
RESEARCHER: Final = "kiw_gamak_research"
SEARCH_TOOL: Final = "kiw_gamak_search_passages"


def retrieval_code(challenge: str) -> str:
    return sha256(f"{SEARCH_TOOL}:{challenge}".encode()).hexdigest()


class SearchReply(Contract):
    retrieval: Retrieval
    execution_code: str
    nifs: NifsReport | None = None
    nifs_release_confirmed: bool | None = None


class ReviewProposal(Contract):
    decision: Decision
    regional_citation: PassageId | None
    government_citation: PassageId | None
