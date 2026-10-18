from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, SecretStr, field_validator

from personal_markets.core.errors import ForbiddenError
from personal_markets.identity.credentials import (
    CredentialMetadata,
    InferencePreference,
    UserProvider,
)
from personal_markets.identity.deps import get_invited_principal
from personal_markets.identity.domain import Principal
from personal_markets.identity.factory import get_inference_settings_service
from personal_markets.identity.inference_settings import InferenceSettingsService

router = APIRouter(prefix="/api/v1/settings/inference", tags=["inference settings"])
Owner = Annotated[Principal, Depends(get_invited_principal)]
Service = Annotated[InferenceSettingsService, Depends(get_inference_settings_service)]


class CredentialBody(BaseModel):
    api_key: SecretStr = Field(min_length=12, max_length=512)

    @field_validator("api_key")
    @classmethod
    def valid_key(cls, value: SecretStr) -> SecretStr:
        key = value.get_secret_value().strip()
        if not 12 <= len(key) <= 512 or any(char.isspace() for char in key):
            raise ValueError("Invalid API key format")
        return SecretStr(key)


def secure_transport(request: Request) -> None:
    from personal_markets.core.config import get_settings

    if get_settings().environment in {"prod", "production"} and request.url.scheme != "https":
        raise ForbiddenError("Provider credentials require HTTPS")


@router.get("")
async def settings(owner: Owner, service: Service, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return await service.view(owner)


@router.put("")
async def preference(
    body: InferencePreference, owner: Owner, service: Service, response: Response
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return await service.set_preference(owner, body)


@router.put(
    "/credentials/{provider}",
    response_model=CredentialMetadata,
    dependencies=[Depends(secure_transport)],
)
async def save_key(
    provider: UserProvider,
    body: CredentialBody,
    owner: Owner,
    service: Service,
    request: Request,
    response: Response,
) -> CredentialMetadata:
    response.headers["Cache-Control"] = "no-store"
    return await service.save_key(
        owner,
        provider,
        body.api_key.get_secret_value().strip(),
        request.client.host if request.client else None,
    )


@router.post(
    "/credentials/{provider}/validate",
    response_model=CredentialMetadata,
    dependencies=[Depends(secure_transport)],
)
async def validate_key(
    provider: UserProvider, owner: Owner, service: Service, request: Request, response: Response
) -> CredentialMetadata:
    response.headers["Cache-Control"] = "no-store"
    return await service.validate_key(
        owner, provider, request.client.host if request.client else None
    )


@router.delete("/credentials/{provider}", status_code=204)
async def delete_key(provider: UserProvider, owner: Owner, service: Service) -> Response:
    await service.delete_key(owner, provider)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
