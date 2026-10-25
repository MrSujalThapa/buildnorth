"""Idempotent public marketplace population for dedicated demo accounts.

Creates owned goals through WorkspaceSeedService, then publishes them with the
normal social visibility path. Does not touch other users' private goals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from personal_markets.identity.domain import Principal, UserProfile, user_id_for_clerk
from personal_markets.profile.parameters import DEFAULT_IDS
from personal_markets.social.service import SocialService
from personal_markets.workspace_seed.service import WorkspaceSeedService


@dataclass(frozen=True, slots=True)
class DemoAccount:
    clerk: str
    username: str
    display_name: str
    bio: str
    goal_keys: tuple[str, ...]


DEMO_ACCOUNTS: tuple[DemoAccount, ...] = (
    DemoAccount(
        clerk="demo-marketplace-maya",
        username="mayachen",
        display_name="Maya Chen",
        bio="Tracking an engineering offer, weekly training, a reading streak and family time.",
        goal_keys=("fde_offer", "run_10k", "reading", "family_dinners"),
    ),
    DemoAccount(
        clerk="demo-marketplace-jordan",
        username="jordanokonkwo",
        display_name="Jordan Okonkwo",
        bio="Building a software product, raising a pre-seed round and growing net worth.",
        goal_keys=("startup_raise", "project", "net_worth"),
    ),
    DemoAccount(
        clerk="demo-marketplace-priya",
        username="priyaraman",
        display_name="Priya Raman",
        bio="Working through a machine learning course and a daily meditation habit.",
        goal_keys=("ml_course", "meditation"),
    ),
)


async def seed_marketplace(
    *,
    identity: Any,
    seeder: WorkspaceSeedService,
    social: SocialService,
    goals: Any,
) -> dict[str, Any]:
    summary: list[dict[str, Any]] = []
    for account in DEMO_ACCOUNTS:
        user_id = user_id_for_clerk(account.clerk)
        principal = Principal(
            user_id=user_id,
            clerk_user_id=account.clerk,
            email=f"{account.username}@demo.playitout.local",
            email_verified=True,
            invited=True,
        )
        await identity.upsert_user(principal)
        await identity.upsert_profile(
            user_id,
            UserProfile(
                display_name=account.display_name,
                username=account.username,
                bio=account.bio,
                parameter_ids=list(DEFAULT_IDS),
            ),
        )
        seeded = await seeder.seed(user_id, keys=account.goal_keys)
        seeded_ids = {row["goal_id"] for row in seeded["goals"]}
        newly_published = 0
        public: list[str] = []
        for goal in await goals.list_goals(owner_id=user_id):
            if str(goal.goal_id) not in seeded_ids:
                continue
            preview = await social.publish_preview(user_id, goal.goal_id)
            if preview.visibility != "public":
                await social.set_visibility(user_id, goal.goal_id, "public")
                newly_published += 1
            public.append(str(goal.goal_id))
        summary.append(
            {
                "username": account.username,
                "user_id": str(user_id),
                "seed": seeded,
                "public_goal_ids": public,
                "newly_published": newly_published,
            }
        )
    return {"accounts": summary}


def demo_user_id(clerk: str) -> UUID:
    return user_id_for_clerk(clerk)
