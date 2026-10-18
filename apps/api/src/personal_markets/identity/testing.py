from personal_markets.identity.domain import Principal, user_id_for_clerk
from personal_markets.identity.tokens import issue_test_token


def make_principal(
    clerk_user_id: str,
    *,
    email: str | None = None,
    invited: bool = False,
    hosted: bool = False,
    role: str = "user",
    quota_usd: float = 2.0,
    quota_tokens: int = 100_000,
) -> Principal:
    return Principal(
        user_id=user_id_for_clerk(clerk_user_id),
        clerk_user_id=clerk_user_id,
        email=email or f"{clerk_user_id}@example.test",
        email_verified=True,
        role=role,  # type: ignore[arg-type]
        invited=bool(invited or hosted),
        hosted_enabled=hosted,
        hosted_quota_usd=quota_usd if hosted else 0.0,
        hosted_quota_tokens=quota_tokens if hosted else 0,
    )


def invited_principal(clerk_user_id: str = "test-user-a") -> Principal:
    return make_principal(clerk_user_id, invited=True, hosted=True)


def admin_principal(clerk_user_id: str = "test-admin") -> Principal:
    return make_principal(clerk_user_id, email="admin@example.test", invited=True, role="admin")


def bearer_for(principal: Principal, secret: str) -> str:
    return issue_test_token(
        secret=secret,
        clerk_user_id=principal.clerk_user_id,
        email=principal.email,
        email_verified=principal.email_verified,
    )
