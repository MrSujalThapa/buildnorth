import hashlib
from uuid import UUID, uuid4

from personal_markets.core.errors import ResourceNotFoundError
from personal_markets.evidence.domain import EvidenceCommit, NormalizedEvidence
from personal_markets.evidence.repository import EvidenceRepository
from personal_markets.ports import EvidenceEventProposal


class EvidenceService:
    def __init__(self, repository: EvidenceRepository) -> None:
        self._repository = repository

    async def list_for_goal(self, goal_id: UUID) -> list[NormalizedEvidence]:
        return await self._repository.list_for_goal(goal_id)

    async def watch_goal(self, goal_id: UUID) -> None:
        track = getattr(self._repository, "track_goal", None)
        if callable(track):
            track(goal_id)

    async def commit(
        self,
        user_id: UUID,
        goal_id: UUID,
        events: list[EvidenceEventProposal],
        agent_run_id: UUID | None,
        conflicts: list[str],
    ) -> EvidenceCommit:
        await self.watch_goal(goal_id)
        goal = await self._repository.goal_exists(goal_id)
        if not goal:
            raise ResourceNotFoundError(f"Goal {goal_id} was not found")
        normalized: list[NormalizedEvidence] = []
        for event in events:
            fingerprint = evidence_fingerprint(user_id, event)
            existing = await self._repository.find_fingerprint(user_id, fingerprint)
            if existing:
                normalized.append(existing)
                continue
            stored = await self._repository.insert(
                user_id=user_id,
                goal_id=goal_id,
                event=event,
                fingerprint=fingerprint,
                agent_run_id=agent_run_id,
                conflict="flagged" if conflicts else "none",
            )
            normalized.append(stored)
        return EvidenceCommit(events=normalized, conflicts=conflicts)


def evidence_fingerprint(user_id: UUID, event: EvidenceEventProposal) -> str:
    canonical = "|".join(
        [
            str(user_id),
            event.source_type,
            event.event_type,
            event.metric,
            event.observed_at,
            "" if event.numeric_value is None else f"{event.numeric_value:.6f}",
            event.categorical_value or "",
            event.summary.strip().lower(),
        ]
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def new_evidence_id() -> UUID:
    return uuid4()
