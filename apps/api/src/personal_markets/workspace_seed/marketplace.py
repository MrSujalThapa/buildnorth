"""Idempotent public marketplace population for dedicated demo accounts.

Creates owned goals through WorkspaceSeedService, then publishes them with the
normal social visibility path. Does not touch other users' private goals.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from personal_markets.identity.domain import Principal, UserProfile, user_id_for_clerk
from personal_markets.identity.factory import get_identity_repository
from personal_markets.profile.parameters import DEFAULT_IDS
from personal_markets.social.service import SocialService
from personal_markets.workspace_seed.service import WorkspaceSeedService

DEMO_ACCOUNTS: tuple[dict[str, str], ...] = (
    {
        "clerk": "demo-marketplace-maya",
        "username": "mayachen",
        "display_name": "Maya Chen",
        "bio": "Tracking a Fall internship, weekly training, and a reading streak.",
    },
    {
        "clerk": "demo-marketplace-jordan",
        "username": "jordanokonkwo",
        "display_name": "Jordan Okonkwo",
        "bio": "Building a software product and keeping an emergency fund on track.",
    },
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
        clerk = account["clerk"]
        user_id = user_id_for_clerk(clerk)
        principal = Principal(
            user_id=user_id,
            clerk_user_id=clerk,
            email=f"{account['username']}@demo.playitout.local",
            email_verified=True,
            invited=True,
        )
        await identity.upsert_user(principal)
        await identity.upsert_profile(
            user_id,
            UserProfile(
                display_name=account["display_name"],
                username=account["username"],
                bio=account["bio"],
                parameter_ids=list(DEFAULT_IDS),
            ),
        )
        seeded = await seeder.seed(user_id)
        published = 0
        for goal in await goals.list_goals(owner_id=user_id):
            preview = await social.publish_preview(user_id, goal.goal_id)
            if preview.visibility != "public":
                await social.set_visibility(user_id, goal.goal_id, "public")
                published += 1
            else:
                published += 1
        summary.append(
            {
                "username": account["username"],
                "user_id": str(user_id),
                "seed": seeded,
                "published_markets": published,
            }
        )
    return {"accounts": summary}


def demo_user_id(clerk: str) -> UUID:
    return user_id_for_clerk(clerk)
