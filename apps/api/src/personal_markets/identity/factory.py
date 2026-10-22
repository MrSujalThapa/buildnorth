from functools import lru_cache
from typing import TYPE_CHECKING

from personal_markets.core.config import get_settings
from personal_markets.identity.budget import (
    InferenceBudgetService,
    InMemoryBudgetStore,
    PostgresBudgetStore,
)
from personal_markets.identity.credentials import CredentialStore
from personal_markets.identity.service import IdentityService
from personal_markets.identity.store import InMemoryIdentityRepository, PostgresIdentityRepository
from personal_markets.persistence.database import create_engine

if TYPE_CHECKING:
    from personal_markets.identity.inference_settings import InferenceSettingsService


def reset_identity_state() -> None:
    get_identity_service.cache_clear()
    get_credential_store.cache_clear()
    get_identity_repository.cache_clear()
    get_budget_store.cache_clear()
    get_identity_repository._memory = InMemoryIdentityRepository()  # type: ignore[attr-defined]
    get_budget_store._memory = InMemoryBudgetStore()  # type: ignore[attr-defined]


@lru_cache
def get_identity_repository():
    memory = getattr(get_identity_repository, "_memory", None)
    if memory is not None:
        return memory
    settings = get_settings()
    if settings.database_url and settings.environment not in {"test", "pytest"}:
        return PostgresIdentityRepository(create_engine(settings.database_url))
    repo = InMemoryIdentityRepository()
    get_identity_repository._memory = repo  # type: ignore[attr-defined]
    return repo


@lru_cache
def get_identity_service() -> IdentityService:
    return IdentityService(get_identity_repository(), get_settings())


@lru_cache
def get_budget_store():
    memory = getattr(get_budget_store, "_memory", None)
    if memory is not None:
        return memory
    settings = get_settings()
    if settings.database_url and settings.environment not in {"test", "pytest"}:
        return PostgresBudgetStore(create_engine(settings.database_url))
    store = InMemoryBudgetStore()
    get_budget_store._memory = store  # type: ignore[attr-defined]
    return store


def get_inference_budget_service() -> InferenceBudgetService:
    return InferenceBudgetService(get_budget_store(), get_settings())


@lru_cache
def get_credential_store() -> CredentialStore:
    from personal_markets.identity.credentials import (
        InMemoryCredentialStore,
        PostgresCredentialStore,
    )

    settings = get_settings()
    if settings.database_url and settings.environment not in {"test", "pytest"}:
        return PostgresCredentialStore(create_engine(settings.database_url))
    return InMemoryCredentialStore()


def get_inference_settings_service() -> "InferenceSettingsService":
    if get_settings().environment in {"test", "pytest"}:
        return _build_inference_settings_service()
    return _production_inference_settings_service()


@lru_cache
def _production_inference_settings_service() -> "InferenceSettingsService":
    return _build_inference_settings_service()


def _build_inference_settings_service() -> "InferenceSettingsService":
    from personal_markets.identity.inference_audit import InferenceAudit
    from personal_markets.identity.inference_settings import InferenceSettingsService

    return InferenceSettingsService(
        get_settings(),
        get_credential_store(),
        get_inference_budget_service(),
        InferenceAudit(get_budget_store()),
    )
