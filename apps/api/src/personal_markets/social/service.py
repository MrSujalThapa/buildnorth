from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from personal_markets.core.errors import ConflictError, ForbiddenError, ResourceNotFoundError
from personal_markets.goals.service import GoalService
from personal_markets.identity.domain import UserProfile, is_demo_persona
from personal_markets.identity.service import IdentityService
from personal_markets.social.blueprint import (
    build_public_blueprint,
    fork_goal,
    history_points,
    reviewed_blueprint,
    success_summary,
)
from personal_markets.social.domain import (
    ActivityDay,
    ForkProvenance,
    OwnerMarketSocial,
    PublicBlueprint,
    PublicCreator,
    PublicForecastState,
    PublicHistoryPoint,
    PublicMarketCard,
    PublicMarketDetail,
    PublicProfile,
    Visibility,
)
from personal_markets.social.repository import SocialRepository
from personal_markets.social.updates import (
    derive_updates,
    modeled_sensitivity,
    new_evidence_ids,
    receipt_facts,
)


def _handle(user_id: UUID, profile: UserProfile) -> str:
    return profile.username or str(user_id)


def _carried_fields(success: dict[str, Any], requirements: dict[str, Any]) -> list[str]:
    fields = ["title", "deadline"]
    if success:
        fields.append("success_criteria")
    for key, name in (
        ("description", "description"),
        ("milestones", "milestones"),
        ("strategy", "strategy"),
    ):
        if success.get(key):
            fields.append(name)
    if requirements.get("life_area"):
        fields.append("category")
    if isinstance(requirements.get("forecast_spec"), dict):
        fields.append("forecast_spec")
    return fields


def _forecast_with_history(
    forecast: PublicForecastState, history: list[PublicHistoryPoint]
) -> PublicForecastState:
    """Published history implies a published market when no later decision exists."""
    if forecast.status == "unpublished" and history:
        return PublicForecastState(status="published")
    return forecast


class SocialService:
    def __init__(
        self,
        repository: SocialRepository,
        goals: GoalService,
        identity: IdentityService,
        photos: Any | None = None,
    ) -> None:
        self._repository = repository
        self._goals = goals
        self._identity = identity
        self._photos = photos

    async def _creator(self, user_id: UUID) -> PublicCreator:
        profile = await self._identity.profile_for_user(user_id)
        has_photo = False
        if self._photos is not None:
            has_photo = await self._photos.get(user_id) is not None
        display = profile.display_name
        return PublicCreator(
            user_id=user_id,
            handle=_handle(user_id, profile),
            username=profile.username,
            display_name=display,
            bio=profile.bio,
            has_photo=has_photo,
            demo_persona=is_demo_persona(user_id),
        )

    async def resolve_handle(self, handle: str) -> UUID:
        trimmed = handle.strip()
        if not trimmed:
            raise ResourceNotFoundError("Profile was not found")
        user_id = await self._identity.user_id_for_handle(trimmed)
        if user_id is None:
            raise ResourceNotFoundError("Profile was not found")
        return user_id

    async def publish_preview(self, owner_id: UUID, goal_id: UUID) -> OwnerMarketSocial:
        goal = await self._goals.get_goal(goal_id, owner_id=owner_id)
        blueprint = build_public_blueprint(goal)
        visibility = await self._repository.visibility(goal_id) or "private"
        published_at = None
        row = await self._repository.get_goal_row(goal_id)
        if row:
            published_at = row.get("published_at")
            if visibility == "public":
                blueprint = self._reviewed_blueprint(row)
        stars = await self._repository.star_counts([goal_id])
        forks = await self._repository.fork_counts([goal_id])
        return OwnerMarketSocial(
            goal_id=goal_id,
            visibility=visibility,
            published_at=published_at,
            star_count=stars.get(goal_id, 0),
            fork_count=forks.get(goal_id, 0),
            public_preview=blueprint,
            fork=await self._fork_from_row(row) if row else None,
        )

    async def set_visibility(
        self, owner_id: UUID, goal_id: UUID, visibility: Visibility
    ) -> OwnerMarketSocial:
        goal = await self._goals.get_goal(goal_id, owner_id=owner_id)
        now = datetime.now(UTC)
        blueprint = build_public_blueprint(goal, snapshot_at=now)
        published_at = now if visibility == "public" else None
        updated = await self._repository.set_visibility(
            goal_id,
            owner_id,
            visibility,
            blueprint.model_dump(mode="json"),
            published_at,
        )
        if not updated:
            raise ForbiddenError("only the owner can change market visibility")
        if visibility == "public":
            await self._repository.record_activity(
                owner_id, "market_published", datetime.now(UTC).date(), goal_id
            )
        return await self.publish_preview(owner_id, goal_id)

    async def owner_stats(
        self, owner_id: UUID, goal_ids: list[UUID]
    ) -> dict[str, OwnerMarketSocial]:
        stars = await self._repository.star_counts(goal_ids)
        forks = await self._repository.fork_counts(goal_ids)
        starred = await self._repository.starred_goal_ids(owner_id, goal_ids)
        items: dict[str, OwnerMarketSocial] = {}
        for goal_id in goal_ids:
            row = await self._repository.get_goal_row(goal_id)
            visibility: Visibility = "private"
            published_at = None
            if row and row["user_id"] == owner_id:
                visibility = row.get("visibility") or "private"
                published_at = row.get("published_at")
            items[str(goal_id)] = OwnerMarketSocial(
                goal_id=goal_id,
                visibility=visibility,
                published_at=published_at,
                star_count=stars.get(goal_id, 0),
                fork_count=forks.get(goal_id, 0),
                starred=goal_id in starred,
                fork=await self._fork_from_row(row) if row else None,
            )
        return items

    async def _cards_from_rows(
        self, rows: list[dict[str, Any]], viewer_id: UUID | None
    ) -> list[PublicMarketCard]:
        goal_ids = [row["id"] for row in rows]
        stars = await self._repository.star_counts(goal_ids)
        forks = await self._repository.fork_counts(goal_ids)
        starred = (
            await self._repository.starred_goal_ids(viewer_id, goal_ids) if viewer_id else set()
        )
        histories = await self._repository.history_for_goals(goal_ids)
        cards: list[PublicMarketCard] = []
        creators: dict[UUID, PublicCreator] = {}
        for row in rows:
            owner_id = row["user_id"]
            if owner_id not in creators:
                creators[owner_id] = await self._creator(owner_id)
            history = history_points(histories.get(row["id"], []))
            blueprint = self._blueprint_for_viewer(row, viewer_id)
            forecast = _forecast_with_history(blueprint.forecast, history)
            latest = history[-1].probability if history and forecast.status == "published" else None
            cards.append(
                PublicMarketCard(
                    goal_id=row["id"],
                    title=row["title"],
                    description=blueprint.description,
                    category=blueprint.category or str(row["goal_type"]),
                    visibility="public" if row.get("visibility") == "public" else "private",
                    creator=creators[owner_id],
                    star_count=stars.get(row["id"], 0),
                    fork_count=forks.get(row["id"], 0),
                    starred=row["id"] in starred,
                    published_at=row.get("published_at"),
                    updated_at=row.get("updated_at"),
                    latest_probability=latest,
                    forecast=forecast,
                    history=history,
                    fork=await self._fork_from_row(row),
                )
            )
        return cards

    async def _fork_from_row(self, row: dict[str, Any] | None) -> ForkProvenance | None:
        if not row or not row.get("forked_from_goal_id"):
            return None
        source_id = row["forked_from_goal_id"]
        source_user = row["forked_from_user_id"]
        source = await self._repository.get_goal_row(source_id)
        public = bool(source and source.get("visibility") == "public")
        handle = None
        title = None
        if public and source:
            creator = await self._creator(source["user_id"])
            handle = creator.handle
            title = source["title"]
        requirements = row.get("model_requirements_json")
        metadata = requirements.get("forked_blueprint") if isinstance(requirements, dict) else None
        carried = metadata.get("carried_fields") if isinstance(metadata, dict) else None
        return ForkProvenance(
            carried_fields=[str(item) for item in carried] if isinstance(carried, list) else [],
            source_goal_id=source_id,
            source_user_id=source_user,
            source_handle=handle,
            source_title=title,
            source_public=public,
            forked_at=row.get("updated_at") or datetime.now(UTC),
        )

    async def search_markets(
        self,
        *,
        query: str | None,
        category: str | None,
        sort: str,
        limit: int,
        offset: int,
        viewer_id: UUID | None,
    ) -> list[PublicMarketCard]:
        rows = await self._repository.search_public(
            query=query, category=category, sort=sort, limit=limit, offset=offset
        )
        return await self._cards_from_rows(rows, viewer_id)

    async def search_markets_page(
        self,
        *,
        query: str | None,
        category: str | None,
        sort: str,
        limit: int,
        offset: int,
        viewer_id: UUID | None,
    ) -> tuple[list[PublicMarketCard], int]:
        items = await self.search_markets(
            query=query,
            category=category,
            sort=sort,
            limit=limit,
            offset=offset,
            viewer_id=viewer_id,
        )
        total = await self._repository.count_public(query=query, category=category)
        return items, total

    @staticmethod
    def _reviewed_blueprint(row: dict[str, Any]) -> PublicBlueprint:
        return reviewed_blueprint(row, live=False)

    @staticmethod
    def _blueprint_for_viewer(row: dict[str, Any], viewer_id: UUID | None) -> PublicBlueprint:
        owner_private = viewer_id == row["user_id"] and row.get("visibility") != "public"
        return reviewed_blueprint(row, live=owner_private)

    async def public_market(self, goal_id: UUID, viewer_id: UUID | None) -> PublicMarketDetail:
        row = await self._repository.get_goal_row(goal_id)
        if row is None:
            raise ResourceNotFoundError("Market was not found")
        owner_id = row["user_id"]
        if row.get("visibility") != "public" and viewer_id != owner_id:
            raise ResourceNotFoundError("Market was not found")
        cards = await self._cards_from_rows([row], viewer_id)
        card = cards[0]
        blueprint = self._blueprint_for_viewer(row, viewer_id).model_copy(
            update={"forecast": card.forecast}
        )
        facts = receipt_facts(await self._repository.published_updates(goal_id))
        wanted = sorted(new_evidence_ids(facts))
        metrics = await self._repository.evidence_metrics(goal_id, wanted) if wanted else {}
        return PublicMarketDetail(
            **card.model_dump(),
            blueprint=blueprint,
            share_path=f"/m/{goal_id}",
            updates=derive_updates(
                facts, tracked_metrics=blueprint.tracked_metrics, evidence_metrics=metrics
            ),
            modeled_sensitivity=modeled_sensitivity(facts),
        )

    async def profile(self, handle: str, viewer_id: UUID | None) -> PublicProfile:
        user_id = await self.resolve_handle(handle)
        creator = await self._creator(user_id)
        followers, following = await self._repository.follow_counts(user_id)
        is_following = bool(viewer_id and await self._repository.following(viewer_id, user_id))
        public_rows = await self._repository.public_goals_for_user(
            user_id, query=None, limit=500, offset=0
        )
        today = datetime.now(UTC).date()
        start = today - timedelta(days=365)
        counts = await self._repository.activity_counts(
            user_id,
            start,
            today,
            public_only=viewer_id != user_id,
            include_fixtures=creator.demo_persona or viewer_id == user_id,
        )
        activity = [ActivityDay(day=day, count=count) for day, count in sorted(counts.items())]
        return PublicProfile(
            creator=creator,
            follower_count=followers,
            following_count=following,
            following=is_following,
            is_self=viewer_id == user_id,
            market_count=len(public_rows),
            contribution_total=sum(counts.values()),
            activity=activity,
        )

    async def profile_markets(
        self,
        handle: str,
        viewer_id: UUID | None,
        *,
        query: str | None,
        visibility: Visibility | None,
        limit: int,
        offset: int,
    ) -> list[PublicMarketCard]:
        user_id = await self.resolve_handle(handle)
        if viewer_id == user_id:
            rows = await self._repository.owner_goals(
                user_id, query=query, visibility=visibility, limit=limit, offset=offset
            )
        else:
            rows = await self._repository.public_goals_for_user(
                user_id, query=query, limit=limit, offset=offset
            )
        return await self._cards_from_rows(rows, viewer_id)

    async def profile_stars(
        self, handle: str, viewer_id: UUID | None, limit: int, offset: int
    ) -> list[PublicMarketCard]:
        user_id = await self.resolve_handle(handle)
        rows = await self._repository.list_starred_public(
            user_id, viewer_id=viewer_id, limit=limit, offset=offset
        )
        return await self._cards_from_rows(rows, viewer_id)

    async def star(self, user_id: UUID, goal_id: UUID) -> dict[str, Any]:
        await self._require_public_or_owner(goal_id, user_id)
        created = await self._repository.star(user_id, goal_id)
        counts = await self._repository.star_counts([goal_id])
        return {"starred": True, "star_count": counts.get(goal_id, 0), "created": created}

    async def unstar(self, user_id: UUID, goal_id: UUID) -> dict[str, Any]:
        await self._repository.unstar(user_id, goal_id)
        counts = await self._repository.star_counts([goal_id])
        return {"starred": False, "star_count": counts.get(goal_id, 0)}

    async def follow(self, follower_id: UUID, handle: str) -> dict[str, Any]:
        followee_id = await self.resolve_handle(handle)
        if follower_id == followee_id:
            raise ConflictError("You cannot follow yourself")
        await self._repository.follow(follower_id, followee_id)
        followers, _following = await self._repository.follow_counts(followee_id)
        return {"following": True, "follower_count": followers}

    async def unfollow(self, follower_id: UUID, handle: str) -> dict[str, Any]:
        followee_id = await self.resolve_handle(handle)
        await self._repository.unfollow(follower_id, followee_id)
        followers, _following = await self._repository.follow_counts(followee_id)
        return {"following": False, "follower_count": followers}

    async def follow_graph(
        self, handle: str, kind: str, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        user_id = await self.resolve_handle(handle)
        rows = (
            await self._repository.followers(user_id, limit, offset)
            if kind == "followers"
            else await self._repository.following_list(user_id, limit, offset)
        )
        items = []
        for other_id, created_at in rows:
            items.append(
                {
                    "creator": (await self._creator(other_id)).model_dump(mode="json"),
                    "created_at": created_at,
                }
            )
        return items

    async def fork(
        self,
        owner_id: UUID,
        source_goal_id: UUID,
        *,
        title: str | None,
        deadline: datetime | None,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        row = await self._repository.get_goal_row(source_goal_id)
        if row is None or row.get("visibility") != "public":
            raise ResourceNotFoundError("Market was not found")
        blueprint = self._reviewed_blueprint(row)
        if not blueprint.success_criteria:
            raise ConflictError("This blueprint has no public success criteria to fork")
        source = await self._goals.get_goal(source_goal_id)
        metric = blueprint.success_criteria.get("metric")
        state_dimensions = list(blueprint.tracked_metrics) or (
            [metric] if isinstance(metric, str) and metric else ["progress"]
        )
        reviewed_requirements: dict[str, Any] = dict(blueprint.model_configuration)
        if blueprint.category and blueprint.category != source.goal_type.value:
            reviewed_requirements["life_area"] = blueprint.category
        if "forecast_spec" in source.model_requirements:
            reviewed_requirements["forecast_spec"] = source.model_requirements["forecast_spec"]
        reviewed_success = dict(blueprint.success_criteria)
        generated = success_summary(blueprint.success_criteria, blueprint.deadline)
        if (
            blueprint.description
            and blueprint.description != generated
            and not reviewed_success.get("description")
        ):
            reviewed_success["description"] = blueprint.description
        if blueprint.milestones and not reviewed_success.get("milestones"):
            reviewed_success["milestones"] = blueprint.milestones
        if blueprint.strategies and not reviewed_success.get("strategy"):
            reviewed_success["strategy"] = blueprint.strategies[0]
        reviewed_source = source.model_copy(
            update={
                "title": blueprint.title,
                "success_definition": reviewed_success,
                "model_requirements": reviewed_requirements,
                "state_dimensions": state_dimensions,
            }
        )
        new_id = uuid4()
        reviewed_deadline = deadline or blueprint.deadline or datetime.now(UTC) + timedelta(days=90)
        forked = fork_goal(
            reviewed_source, owner_title=title, deadline=reviewed_deadline, new_goal_id=new_id
        )
        carried = _carried_fields(forked.success_definition, forked.model_requirements)
        if blueprint.tracked_metrics:
            carried.append("tracked_metrics")
        forked = forked.model_copy(
            update={
                "model_requirements": {
                    **forked.model_requirements,
                    "forked_blueprint": {
                        "source_goal_id": str(source_goal_id),
                        "source_title": blueprint.title,
                        "source_blueprint_version": blueprint.blueprint_version,
                        "source_snapshot_at": (
                            blueprint.snapshot_at.isoformat() if blueprint.snapshot_at else None
                        ),
                        "carried_fields": carried,
                        "forked_at": datetime.now(UTC).isoformat(),
                    },
                }
            }
        )
        stored, created = await self._repository.create_fork(
            goal_id=forked.goal_id,
            owner_id=owner_id,
            title=forked.title,
            goal_type=forked.goal_type.value,
            success_definition=forked.success_definition,
            deadline=forked.deadline,
            resource_constraints=forked.resource_constraints.model_dump(mode="json"),
            state_dimensions=list(forked.state_dimensions),
            model_requirements=forked.model_requirements,
            source_goal_id=source_goal_id,
            source_user_id=row["user_id"],
            idempotency_key=idempotency_key,
        )
        await self._repository.record_activity(
            owner_id, "market_created", datetime.now(UTC).date(), stored["id"]
        )
        return {
            "goal_id": str(stored["id"]),
            "created": created,
            "visibility": "private",
            "forked_from": str(source_goal_id),
            "carried_fields": carried,
        }

    async def record_goal_created(self, user_id: UUID, goal_id: UUID) -> None:
        await self._repository.record_activity(
            user_id, "market_created", datetime.now(UTC).date(), goal_id
        )

    async def record_evidence(self, user_id: UUID, goal_id: UUID) -> None:
        await self._repository.record_activity(
            user_id, "evidence_accepted", datetime.now(UTC).date(), goal_id
        )

    async def discover_creators(self, limit: int) -> list[PublicCreator]:
        user_ids = await self._repository.discover_creators(limit)
        return [await self._creator(user_id) for user_id in user_ids]

    async def _require_public_or_owner(self, goal_id: UUID, user_id: UUID) -> None:
        visibility = await self._repository.visibility(goal_id)
        owner_id = await self._repository.owner_id(goal_id)
        if visibility is None or owner_id is None:
            raise ResourceNotFoundError("Market was not found")
        if visibility != "public" and owner_id != user_id:
            raise ResourceNotFoundError("Market was not found")

    def share_url(self, goal_id: UUID, origin: str) -> str:
        return f"{origin.rstrip('/')}/m/{goal_id}"
