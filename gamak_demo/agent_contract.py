"""Schema for the read-only IBM reply before the backend commits a draft."""
from __future__ import annotations

from hashlib import sha256
from typing import Final

from .contract import Assessment, Contract, Decision, EvidenceId

TOOL_NAME: Final = "kiw_gamak_official_evidence"
AGENT_NAME: Final = "kiw_gamak_red_tide"


def execution_code(challenge: str) -> str:
    return sha256(f"{TOOL_NAME}:{challenge}".encode()).hexdigest()


class AgentReply(Contract):
    assessment: Assessment
    execution_code: str


class AgentProposal(Contract):
    decision: Decision
    evidence_ids: tuple[EvidenceId, ...]
