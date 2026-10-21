from personal_markets.identity.clerk_users import VerifiedEmailCache


def test_verified_email_cache_reuses_short_lived_lookup_and_expires() -> None:
    current = [0.0]
    calls: list[str] = []

    def lookup(user_id: str, secret: str) -> tuple[str, bool]:
        calls.append(user_id)
        return "reader@example.com", True

    cache = VerifiedEmailCache(lookup, ttl_seconds=60, clock=lambda: current[0])
    assert cache.resolve("clerk-user", "secret") == ("reader@example.com", True)
    assert cache.resolve("clerk-user", "secret") == ("reader@example.com", True)
    assert calls == ["clerk-user"]
    current[0] = 61
    assert cache.resolve("clerk-user", "secret") == ("reader@example.com", True)
    assert calls == ["clerk-user", "clerk-user"]


def test_unverified_email_is_not_cached() -> None:
    calls = [0]

    def lookup(_user_id: str, _secret: str) -> tuple[str, bool]:
        calls[0] += 1
        return "reader@example.com", False

    cache = VerifiedEmailCache(lookup)
    assert cache.resolve("clerk-user", "secret") == ("reader@example.com", False)
    assert cache.resolve("clerk-user", "secret") == ("reader@example.com", False)
    assert calls[0] == 2
