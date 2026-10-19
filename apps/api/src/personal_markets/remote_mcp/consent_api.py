"""Clerk-authenticated endpoints for consent and connection management.

These run with the normal PlayItOut session (never an MCP token) and never return
access or refresh tokens.
"""

from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from pydantic import BaseModel, Field

from personal_markets.core.config import get_settings
from personal_markets.identity.deps import get_invited_principal
from personal_markets.identity.domain import Principal
from personal_markets.remote_mcp.oauth import (
    AuthorizationRequestView,
    ConnectionView,
    RemoteMcpAuthorization,
    ScopeView,
    scope_views,
)
from personal_markets.remote_mcp.scopes import ALL_SCOPES, DEFAULT_SCOPES, TOOL_SCOPES

if TYPE_CHECKING:
    from personal_markets.remote_mcp.server import RemoteMcp

router = APIRouter(prefix="/api/v1/mcp", tags=["remote-mcp"])
PrincipalDep = Annotated[Principal, Depends(get_invited_principal)]


class McpStatus(BaseModel):
    enabled: bool
    endpoint: str
    transport: str = "streamable-http"
    auth: str = "oauth2.1+pkce"
    dynamic_client_registration: bool
    scopes: list[ScopeView]
    default_scopes: list[str]
    public_https: bool
    tools: list[str]


class DecisionBody(BaseModel):
    approve: bool
    scopes: list[str] | None = Field(default=None, max_length=len(ALL_SCOPES))


class DecisionResult(BaseModel):
    redirect_url: str


def _authorization(request: Request) -> RemoteMcpAuthorization:
    remote: RemoteMcp | None = getattr(request.app.state, "remote_mcp", None)
    if remote is None:
        raise HTTPException(status_code=404, detail="Personal agent connections are disabled")
    return remote.authorization


@router.get("/status", response_model=McpStatus)
async def status(request: Request, _principal: PrincipalDep) -> McpStatus:
    settings = get_settings()
    remote = getattr(request.app.state, "remote_mcp", None)
    endpoint = f"{settings.public_api_url.rstrip('/')}/mcp"
    tools = sorted(TOOL_SCOPES) if remote else []
    return McpStatus(
        enabled=remote is not None,
        endpoint=endpoint,
        dynamic_client_registration=settings.mcp_dynamic_client_registration,
        scopes=scope_views(list(ALL_SCOPES)),
        default_scopes=list(DEFAULT_SCOPES),
        public_https=endpoint.startswith("https://"),
        tools=tools,
    )


@router.get("/authorization-requests/{request_id}", response_model=AuthorizationRequestView)
async def describe(
    request_id: Annotated[str, Path(max_length=64)],
    request: Request,
    response: Response,
    principal: PrincipalDep,
) -> AuthorizationRequestView:
    response.headers["Cache-Control"] = "no-store"
    return await _authorization(request).describe_request(request_id, principal)


@router.post("/authorization-requests/{request_id}/decision", response_model=DecisionResult)
async def decide(
    request_id: Annotated[str, Path(max_length=64)],
    body: DecisionBody,
    request: Request,
    response: Response,
    principal: PrincipalDep,
) -> DecisionResult:
    response.headers["Cache-Control"] = "no-store"
    url = await _authorization(request).decide(
        request_id, principal, approve=body.approve, scopes=body.scopes
    )
    return DecisionResult(redirect_url=url)


@router.get("/connections", response_model=list[ConnectionView])
async def connections(request: Request, principal: PrincipalDep) -> list[ConnectionView]:
    return await _authorization(request).list_connections(principal)


@router.delete("/connections/{connection_id}", response_model=ConnectionView)
async def revoke(connection_id: UUID, request: Request, principal: PrincipalDep) -> ConnectionView:
    return await _authorization(request).revoke_connection(principal, connection_id)
