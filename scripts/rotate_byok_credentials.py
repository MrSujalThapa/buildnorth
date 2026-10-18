"""Operator-only AEAD rotation. Configure a new active key and retain the old key ring.

No plaintext, ciphertext or identities are printed. The transaction rolls back if
any credential cannot authenticate. Always take a protected DB/key backup first.
"""

import argparse
from uuid import UUID, uuid4

import psycopg

from personal_markets.core.config import Settings
from personal_markets.identity.credentials import CredentialCipher


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Commit credential re-encryption")
    execute = parser.parse_args().execute
    settings = Settings()
    if not settings.database_url:
        parser.error("PM_DATABASE_URL is required")
    cipher = CredentialCipher(settings.byok_encryption_keys, settings.byok_active_key_id)
    cipher.encrypt(UUID(int=0), "openai", "configuration-check")
    with psycopg.connect(settings.database_url) as connection:
        rows = connection.execute(
            "select user_id, provider, ciphertext from provider_credentials for update"
        ).fetchall()
        replacements = [
            (
                cipher.encrypt(owner, provider, cipher.decrypt(owner, provider, ciphertext)),
                uuid4(),
                owner,
                provider,
            )
            for owner, provider, ciphertext in rows
            if not ciphertext.startswith(settings.byok_active_key_id + ":")
        ]
        if execute:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    update provider_credentials set ciphertext=%s, version=%s
                    where user_id=%s and provider=%s
                """,
                    replacements,
                )
        else:
            connection.rollback()
    print(f"{'Rotated' if execute else 'Validated for rotation'} {len(replacements)} credentials")


if __name__ == "__main__":
    main()
