import hashlib
from uuid import UUID, uuid4

from personal_markets.core.errors import ResourceNotFoundError, SemanticProviderError
from personal_markets.evidence.domain import EvidenceCommit, NormalizedEvidence, SubmissionContext
from personal_markets.evidence.metrics import (
    canonicalize_event,
    observation_kind,
    parse_observed_at,
    period_key,
)
from personal_markets.evidence.repository import EvidenceRepository
from personal_markets.ports import EvidenceEventProposal


class EvidenceService:
    def __init__(self, repository: EvidenceRepository) -> None:
        self._repository = repository

    async def list_for_goal(self, goal_id: UUID) -> list[NormalizedEvidence]:
        return await self._repository.list_for_goal(goal_id)

    async def list_for_goals(self, goal_ids: list[UUID]) -> dict[UUID, list[NormalizedEvidence]]:
        return await self._repository.list_for_goals(goal_ids)

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
        submission: SubmissionContext | None = None,
    ) -> EvidenceCommit:
        await self.watch_goal(goal_id)
        goal = await self._repository.goal_exists(goal_id)
        if not goal:
            raise ResourceNotFoundError(f"Goal {goal_id} was not found")
        normalized: list[NormalizedEvidence] = []
        if any(event.observation_kind == "uncertain" for event in events):
            raise SemanticProviderError("Clarify observation aggregation before committing evidence")
        if submission is None and any(event.source_type == "personal_agent" for event in events):
            raise SemanticProviderError(
                "personal_agent evidence can only arrive through an authorized connection"
            )
        # Only pass the submission context through when present, so repositories that
        # predate external channels keep their original call shape.
        extra = {"submission": submission} if submission is not None else {}
        for event in events:
            event = canonicalize_event(event)
            fingerprint = evidence_fingerprint(user_id, event, goal_id=goal_id)
            existing = await self._repository.find_fingerprint(user_id, fingerprint)
            if existing and existing.evidence_id is not None:
                await self._repository.link_goal(goal_id, existing.evidence_id)
                recorded = await self._repository.record_corroboration(existing, event, **extra)
                normalized.append(recorded)
                continue
            stored = await self._repository.insert(
                user_id=user_id,
                goal_id=goal_id,
                event=event,
                fingerprint=fingerprint,
                agent_run_id=agent_run_id,
                conflict="flagged" if conflicts else "none",
                **extra,
            )
            normalized.append(stored)
        return EvidenceCommit(events=normalized, conflicts=conflicts)


def evidence_fingerprint(
    user_id: UUID, event: EvidenceEventProposal, goal_id: UUID | None = None
) -> str:
    event = canonicalize_event(event)
    kind = observation_kind(event.metric, event.event_type, event.observation_kind)
    observed = parse_observed_at(event.observed_at)
    # Source, event type and summary are provenance, not identity. Period/day
    # keys keep distinct increments and weekly/monthly readings from collapsing.
    parts = [
            str(user_id),
            str(goal_id or ""),
            kind,
            event.metric,
            period_key(kind, event.metric, observed),
            "" if event.numeric_value is None else f"{event.numeric_value:.6f}",
            event.categorical_value or "",
        ]
    if event.event_identity:
        parts.append(event.event_identity)
    canonical = "|".join(parts)
    return hashlib.sha256(canonical.encode()).hexdigest()


def new_evidence_id() -> UUID:
    return uuid4()
