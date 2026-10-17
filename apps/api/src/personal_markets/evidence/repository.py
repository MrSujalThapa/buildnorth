from typing import Protocol
from uuid import UUID

from personal_markets.evidence.domain import NormalizedEvidence
from personal_markets.ports import EvidenceEventProposal


class EvidenceRepository(Protocol):
    async def goal_exists(self, goal_id: UUID) -> bool: ...

    async def list_for_goal(self, goal_id: UUID) -> list[NormalizedEvidence]: ...

    async def find_fingerprint(
        self, user_id: UUID, fingerprint: str
    ) -> NormalizedEvidence | None: ...

    async def insert(
        self,
        user_id: UUID,
        goal_id: UUID,
        event: EvidenceEventProposal,
        fingerprint: str,
        agent_run_id: UUID | None,
        conflict: str,
    ) -> NormalizedEvidence: ...

    async def link_goal(self, goal_id: UUID, evidence_id: UUID) -> None: ...

    async def record_corroboration(
        self, existing: NormalizedEvidence, event: EvidenceEventProposal
    ) -> NormalizedEvidence: ...
