"""Remote MCP endpoint at /mcp using the official MCP Python SDK.

Transport is Streamable HTTP in stateless JSON mode: every POST is self-contained,
which matches the current protocol revision (no protocol-level sessions) and still
serves clients that perform the legacy initialize handshake.
"""

import base64
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any, TypeVar, cast
from urllib.parse import urlsplit
from uuid import UUID

import structlog
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware, get_access_token
from mcp.server.auth.middleware.bearer_auth import (
    AuthenticatedUser,
    BearerAuthBackend,
    RequireAuthMiddleware,
)
from mcp.server.auth.middleware.client_auth import AuthenticationError, ClientAuthenticator
from mcp.server.auth.routes import (
    build_resource_metadata_url,
    cors_middleware,
    create_auth_routes,
    create_protected_resource_routes,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import MCPServer
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp, StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import CallToolResult, ImageContent, TextContent, ToolAnnotations
from pydantic import AnyHttpUrl, Field
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from personal_markets.core.config import Settings
from personal_markets.identity.domain import Principal
from personal_markets.remote_mcp.oauth import RemoteMcpAuthorization
from personal_markets.remote_mcp.odds_app import (
    ODDS_UI_URI,
    UI_EXTENSION_ID,
    build_odds_apps,
)
from personal_markets.remote_mcp.policy import ObservationPolicy
from personal_markets.remote_mcp.scopes import ALL_SCOPES, DEFAULT_SCOPES, TOOL_SCOPES
from personal_markets.remote_mcp.store import RemoteMcpStore
from personal_markets.remote_mcp.tools import (
    Caller,
    ChangeInput,
    EvidenceSummary,
    ForecastCompare,
    ForecastHistory,
    ForecastReadiness,
    ForecastView,
    GoalCreationView,
    GoalDetail,
    GoalList,
    InterventionRanking,
    MilestoneList,
    OddsChartView,
    RemoteMcpTools,
    ScenarioCompare,
    SimulationView,
    StructuredRow,
    SubmissionResult,
    ToolFailure,
)

log = structlog.get_logger("personal_markets.remote_mcp")
_T = TypeVar("_T")

INSTRUCTIONS = """PlayItOut prices personal goals with deterministic models.
Probabilities come from the model, never from you or from PlayItOut's agents.
Choose tools from the user's intent before calling one. "I did X" is an observation:
list_goals/get_goal to identify the owned goal, get_observation_policy for units and
snapshot/increment semantics, then confirm a write before submitting it. "What if I
did X" is hypothetical: use simulate_intervention or compare_scenarios only if the
user supplied a quantified change matching a model parameter; never submit evidence.
For "odds before X", read get_evidence_summary to identify the observation and use
compare_forecasts with evidence_id. For actual-versus-simulated, read get_forecast
and compare_forecasts separately from SimulationView; hypothetical odds are not receipts.
For missing evidence, use get_forecast_readiness and get_observation_policy.
Do not infer a goal from a vague request when multiple goals match. Ask which goal.
Do not guess missing quantities, units, relative dates, or the scope of a follow-up.
The current MCP tools do not search public blueprints or interpret unquantified
natural-language What If actions. Say so rather than fabricating an answer.
Repeated reports of the same observation should be inspected with
get_evidence_summary before writing. Reuse the same idempotency key for a retry;
a fresh key can represent a new increment. Never turn a source mention into proof
of an interview, offer, or rejection without a supported observation.
Progress is evidence, not a contract edit. Title, deadline, and success definition
cannot be rewritten here. Prefer structured evidence: it needs no model call.
Do not fetch private URLs. Evidence is agent-reported; you cannot mark it verified.
compare_forecasts reads published receipts only and will say when none exists.
Observation, receipt publication, and hypothetical times are distinct. Scenarios
never change the published forecast. Interactive
charts require an MCP Apps host; otherwise call get_odds_chart_image for a static PNG."""

_READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
_WRITE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)

GoalId = Annotated[str, Field(description="Goal UUID from list_goals", max_length=64)]
IdempotencyKey = Annotated[
    str,
    Field(
        description="Client-generated key, unique per observation. Retrying with the same "
        "key never double counts.",
        min_length=8,
        max_length=128,
    ),
]
SourceCategory = Annotated[
    str,
    Field(
        description="Where the agent learned this, for example 'email', 'calendar', "
        "'job_board', 'user_message'. Informational only; it does not change trust.",
        min_length=2,
        max_length=40,
        pattern=r"^[a-z0-9_\-]+$",
    ),
]
OptionalRef = Annotated[str | None, Field(default=None, max_length=300)]


def _error_result(failure: ToolFailure) -> CallToolResult:
    payload = failure.payload()
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload))],
        structured_content=payload,
        is_error=True,
    )


class _ScopedRequireAuth(RequireAuthMiddleware):
    """Adds the scope hint the MCP authorization spec recommends on 401 challenges."""

    async def _send_auth_error(
        self, send: Send, status_code: int, error: str, description: str
    ) -> None:
        parts = [f'error="{error}"', f'error_description="{description}"']
        if status_code == 401:
            parts.append(f'scope="{" ".join(DEFAULT_SCOPES)}"')
        if self.resource_metadata_url:
            parts.append(f'resource_metadata="{self.resource_metadata_url}"')
        body = json.dumps({"error": error, "error_description": description}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"www-authenticate", f"Bearer {', '.join(parts)}".encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class McpGateway:
    """Bounds request size and challenges for missing tool scopes before dispatch."""

    def __init__(self, app: ASGIApp, *, max_bytes: int, metadata_url: str) -> None:
        self._app = app
        self._max_bytes = max_bytes
        self._metadata_url = metadata_url

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") != "POST":
            await self._app(scope, receive, send)
            return
        body = bytearray()
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self._max_bytes:
                await self._json(send, 413, {"error": "request_too_large"})
                return
            more = bool(message.get("more_body"))
        needed = _required_scopes(bytes(body))
        user = scope.get("user")
        granted = set(user.access_token.scopes) if isinstance(user, AuthenticatedUser) else set()
        missing = [item for item in needed if item not in granted]
        if missing:
            wanted = " ".join(sorted(granted | set(needed)))
            challenge = (
                f'Bearer error="insufficient_scope", scope="{wanted}", '
                f'resource_metadata="{self._metadata_url}", '
                f'error_description="Requires {" ".join(missing)}"'
            )
            await self._json(
                send,
                403,
                {"error": "insufficient_scope", "error_description": f"Requires {missing[0]}"},
                [(b"www-authenticate", challenge.encode())],
            )
            return
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self._app(scope, replay, send)

    @staticmethod
    async def _json(
        send: Send,
        status: int,
        payload: dict[str, Any],
        extra: list[tuple[bytes, bytes]] | None = None,
    ) -> None:
        data = json.dumps(payload).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(data)).encode()),
                    *(extra or []),
                ],
            }
        )
        await send({"type": "http.response.body", "body": data})


def _required_scopes(body: bytes) -> list[str]:
    try:
        parsed = json.loads(body or b"null")
    except ValueError:
        return []
    messages = parsed if isinstance(parsed, list) else [parsed]
    needed: list[str] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("method") != "tools/call":
            continue
        params = message.get("params")
        name = params.get("name") if isinstance(params, dict) else None
        for item in TOOL_SCOPES.get(str(name), ()):
            if item not in needed:
                needed.append(item)
    return needed


def _revocation_route(authorization: RemoteMcpAuthorization) -> Route:
    """RFC 7009 revocation where public clients may omit client_secret.

    The SDK's handler models client_secret as required, which rejects PKCE public clients.
    """
    authenticator = ClientAuthenticator(authorization)

    async def revoke(request: Request) -> Response:
        try:
            client = await authenticator.authenticate_request(request)
        except AuthenticationError as error:
            return JSONResponse(
                {"error": "unauthorized_client", "error_description": error.message}, 401
            )
        form = await request.form()
        token = form.get("token")
        if not isinstance(token, str) or not token or len(token) > 512:
            return JSONResponse({"error": "invalid_request"}, 400)
        found: Any = await authorization.load_access_token(token)
        if found is None:
            found = await authorization.load_refresh_token(client, token)
        if found is not None and found.client_id == client.client_id:
            await authorization.revoke_token(found)
        return Response(status_code=200, headers={"Cache-Control": "no-store"})

    return Route(
        "/revoke", cors_middleware(revoke, ["POST", "OPTIONS"]), methods=["POST", "OPTIONS"]
    )


def _host_patterns(*urls: str) -> list[str]:
    hosts = {"127.0.0.1:*", "localhost:*", "[::1]:*"}
    for url in urls:
        parts = urlsplit(url)
        if parts.hostname:
            hosts.add(parts.netloc)
            hosts.add(parts.hostname)
    return sorted(hosts)


def _origin_patterns(settings: Settings) -> list[str]:
    origins = {"http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"}
    for url in [settings.public_web_url, settings.public_api_url, *settings.cors_origins]:
        parts = urlsplit(url)
        if parts.scheme and parts.netloc:
            origins.add(f"{parts.scheme}://{parts.netloc}")
    return sorted(origins)


@dataclass
class RemoteMcp:
    authorization: RemoteMcpAuthorization
    tools: RemoteMcpTools
    server: MCPServer
    session_manager: StreamableHTTPSessionManager
    routes: list[BaseRoute]


def build_remote_mcp(
    *,
    settings: Settings,
    store: RemoteMcpStore,
    users: Callable[[UUID], Any],
    tools: RemoteMcpTools,
) -> RemoteMcp:
    authorization = RemoteMcpAuthorization(store, settings, users)
    issuer = AnyHttpUrl(authorization.issuer)
    resource = AnyHttpUrl(authorization.resource)
    auth = AuthSettings(
        issuer_url=issuer,
        resource_server_url=resource,
        required_scopes=None,
        client_registration_options=ClientRegistrationOptions(
            enabled=settings.mcp_dynamic_client_registration,
            valid_scopes=list(ALL_SCOPES),
            # A client's registration bounds what it may later request (including step-up
            # to inference:use); what is actually granted is decided by the user at consent.
            default_scopes=list(ALL_SCOPES),
        ),
        revocation_options=RevocationOptions(enabled=True),
        validate_token_resource=True,
    )
    server = MCPServer(
        name="PlayItOut",
        title="PlayItOut forecasting",
        instructions=INSTRUCTIONS,
        version="0.5.0",
        auth_server_provider=authorization,
        auth=auth,
        extensions=[build_odds_apps()],
    )
    _advertise_ui_on_handshake(server)
    _register_tools(server, tools, users, store)
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_host_patterns(settings.public_api_url),
        allowed_origins=_origin_patterns(settings),
    )
    # Builds the SDK session manager; the SDK's own Starlette wrapper is not used so the
    # protected-resource metadata can advertise every scope and the gateway can sit in front.
    server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        transport_security=security,
        max_request_body_size=settings.mcp_max_request_bytes,
    )
    manager = server.session_manager
    metadata_url = build_resource_metadata_url(resource)
    endpoint: ASGIApp = StreamableHTTPASGIApp(manager)
    endpoint = McpGateway(
        endpoint, max_bytes=settings.mcp_max_request_bytes, metadata_url=str(metadata_url)
    )
    endpoint = _ScopedRequireAuth(endpoint, [], metadata_url)
    endpoint = AuthContextMiddleware(endpoint)
    endpoint = AuthenticationMiddleware(
        endpoint, backend=BearerAuthBackend(authorization, resource_server_url=resource)
    )
    auth_routes = [
        route
        for route in create_auth_routes(
            provider=authorization,
            issuer_url=issuer,
            client_registration_options=auth.client_registration_options,
            revocation_options=auth.revocation_options,
        )
        if getattr(route, "path", None) != "/revoke"
    ]
    routes: list[BaseRoute] = [
        *auth_routes,
        _revocation_route(authorization),
        *create_protected_resource_routes(
            resource_url=resource,
            authorization_servers=[issuer],
            scopes_supported=list(ALL_SCOPES),
            resource_name="PlayItOut",
        ),
        Route("/mcp", endpoint=endpoint, methods=["GET", "POST", "DELETE"]),
    ]
    return RemoteMcp(authorization, tools, server, manager, routes)


def _register_tools(
    server: MCPServer, tools: RemoteMcpTools, users: Callable[[UUID], Any], store: RemoteMcpStore
) -> None:
    async def caller() -> Caller:
        token = get_access_token()
        if token is None or token.subject is None:
            raise ToolFailure("unauthenticated", "Authentication required")
        principal: Principal | None = await users(UUID(token.subject))
        connection_id = UUID(str((token.claims or {}).get("connection_id")))
        connection = await store.get_connection(connection_id)
        if principal is None or connection is None or connection.revoked_at is not None:
            raise ToolFailure("unauthenticated", "This connection is no longer valid")
        return Caller(
            principal=principal,
            connection_id=connection_id,
            client_id=token.client_id,
            client_name=connection.client_name,
            scopes=frozenset(token.scopes),
        )

    async def run(
        name: str,
        operation: Callable[[Caller], Awaitable[_T]],
        *,
        write: bool = False,
        inference: bool = False,
    ) -> _T:
        # The SDK returns a CallToolResult unchanged instead of validating it as _T.
        try:
            who = await caller()
        except ToolFailure as failure:
            return cast(_T, _error_result(failure))
        try:
            tools.require_scope(who, *TOOL_SCOPES[name])
            await tools.rate_limit(who, name, write=write, inference=inference)
            result = await operation(who)
        except ToolFailure as failure:
            await tools.audit(who, name, failure.code)
            return cast(_T, _error_result(failure))
        except Exception as error:
            log.warning("mcp_tool_error", tool=name, error_type=type(error).__name__)
            await tools.audit(who, name, "internal_error")
            internal = ToolFailure(
                "internal_error", "The request could not be completed.", retryable=True
            )
            return cast(_T, _error_result(internal))
        await tools.audit(who, name, "ok")
        return result

    @server.tool(annotations=_READ, title="List goals")
    async def list_goals(
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
        cursor: Annotated[str | None, Field(max_length=12)] = None,
    ) -> GoalList:
        """List your goals, newest first, with their forecast status. Paginated."""
        return await run("list_goals", lambda who: tools.list_goals(who, limit, cursor))

    @server.tool(annotations=_READ, title="Get goal")
    async def get_goal(goal_id: GoalId) -> GoalDetail:
        """Read one goal's contract: success definition, deadline and model family."""
        return await run("get_goal", lambda who: tools.get_goal(who, goal_id))

    @server.tool(annotations=_READ, title="Get forecast readiness")
    async def get_forecast_readiness(goal_id: GoalId) -> ForecastReadiness:
        """Whether PlayItOut has published a forecast, which inputs are still missing,
        and the stored spec status. Does not invent a probability."""
        return await run(
            "get_forecast_readiness", lambda who: tools.get_forecast_readiness(who, goal_id)
        )

    @server.tool(annotations=_READ, title="List milestones")
    async def list_milestones(goal_id: GoalId) -> MilestoneList:
        """Stored milestone nodes on the goal's forecast spec. Empty when the model
        has no milestone graph. Progress is updated with evidence tools, not here."""
        return await run("list_milestones", lambda who: tools.list_milestones(who, goal_id))

    @server.tool(annotations=_READ, title="Get forecast")
    async def get_forecast(goal_id: GoalId) -> ForecastView:
        """Latest stored published receipt: probability, receipt ID, publication time,
        model version, evidence watermark and limitations. Check get_goal for the
        goal's current forecast status. Returns NOT_PUBLISHED when no receipt exists."""
        return await run("get_forecast", lambda who: tools.get_forecast(who, goal_id))

    @server.tool(annotations=_READ, title="Get forecast history")
    async def get_forecast_history(
        goal_id: GoalId, limit: Annotated[int, Field(ge=1, le=100)] = 30
    ) -> ForecastHistory:
        """Stored published receipts for one owned goal, oldest first. Each point has a
        receipt ID, model version, evidence watermark and publication timestamp."""
        return await run(
            "get_forecast_history", lambda who: tools.get_forecast_history(who, goal_id, limit)
        )

    @server.tool(annotations=_READ, title="Get evidence summary")
    async def get_evidence_summary(
        goal_id: GoalId, limit: Annotated[int, Field(ge=1, le=50)] = 20
    ) -> EvidenceSummary:
        """Recent observations for one owned goal: source, verification status,
        observed_at and agent receipt time. Read before resubmitting a possible duplicate."""
        return await run(
            "get_evidence_summary", lambda who: tools.get_evidence_summary(who, goal_id, limit)
        )

    @server.tool(annotations=_READ, title="Get observation policy")
    async def get_observation_policy(goal_id: GoalId) -> ObservationPolicy:
        """Which metrics this goal's model accepts, their units, accepted observation kinds
        (snapshot, increment, period) and validation rules. Call before submitting evidence."""
        return await run(
            "get_observation_policy", lambda who: tools.get_observation_policy(who, goal_id)
        )

    @server.tool(annotations=_READ, title="Get best interventions")
    async def get_best_interventions(goal_id: GoalId) -> InterventionRanking:
        """Interventions ranked by simulated uplift, only when their effects are fitted or
        reference-derived. Otherwise returns UNAVAILABLE with the reason."""
        return await run(
            "get_best_interventions", lambda who: tools.get_best_interventions(who, goal_id)
        )

    @server.tool(annotations=_WRITE, title="Submit structured evidence")
    async def submit_structured_evidence(
        goal_id: GoalId,
        metric: Annotated[str, Field(min_length=1, max_length=80)],
        value: Annotated[float, Field(allow_inf_nan=False, ge=-1e12, le=1e12)],
        unit: Annotated[str, Field(min_length=1, max_length=40)],
        observation_kind: Annotated[
            str, Field(pattern=r"^(snapshot|increment|period)$", description="See policy")
        ],
        idempotency_key: IdempotencyKey,
        source_category: SourceCategory,
        observed_at: Annotated[str | None, Field(default=None, max_length=40)] = None,
        period: Annotated[str | None, Field(default=None, max_length=10)] = None,
        source_identifier: OptionalRef = None,
        supporting_reference: OptionalRef = None,
        note: Annotated[str | None, Field(default=None, max_length=200)] = None,
    ) -> SubmissionResult:
        """Write a confirmed real observation, never a proposed What If action.
        Call get_observation_policy first. No model call. Validated against
        get_observation_policy, de-duplicated, then the forecast is republished if the model
        can price it. An identical snapshot may corroborate without a new receipt;
        increments need a stable key on retries or they can double count. Returns
        the publication status or why repricing did not happen."""
        return await run(
            "submit_structured_evidence",
            lambda who: tools.submit_structured_evidence(
                who,
                goal_id=goal_id,
                metric=metric,
                value=value,
                unit=unit,
                observation_kind=observation_kind,
                idempotency_key=idempotency_key,
                source_category=source_category,
                observed_at=observed_at,
                period=period,
                source_identifier=source_identifier,
                supporting_reference=supporting_reference,
                note=note,
            ),
            write=True,
        )

    @server.tool(annotations=_WRITE, title="Submit observation (natural language)")
    async def submit_observation(
        goal_id: GoalId,
        text: Annotated[str, Field(min_length=3, max_length=2000)],
        idempotency_key: IdempotencyKey,
        source_category: SourceCategory,
        source_identifier: OptionalRef = None,
        supporting_reference: OptionalRef = None,
    ) -> SubmissionResult:
        """Write confirmed past or current evidence described in free text, never a
        hypothetical question. Interpret with PlayItOut's Evidence Agent, then commit like
        structured
        evidence. Uses the account's model credits or its own provider key and needs the
        inference:use permission. Ambiguous text is not committed; clarifying questions are
        returned instead."""
        return await run(
            "submit_observation",
            lambda who: tools.submit_observation(
                who,
                goal_id=goal_id,
                text=text,
                idempotency_key=idempotency_key,
                source_category=source_category,
                source_identifier=source_identifier,
                supporting_reference=supporting_reference,
            ),
            write=True,
            inference=True,
        )

    @server.tool(annotations=_READ, title="Simulate intervention")
    async def simulate_intervention(
        goal_id: GoalId,
        changes: Annotated[list[ChangeInput], Field(min_length=1, max_length=5)],
    ) -> SimulationView:
        """Read-only hypothetical What If with explicit quantified parameter changes (for example
        applications_per_week add 3). Returns the published baseline, scenario probability and
        delta in percentage points. Never changes the published forecast. Changes that map to
        no model parameter return NOT_PRICED with causal_status unmapped_intervention.
        This tool does not parse free text or accept a duration; ask for missing quantities
        and do not silently reinterpret 'stop for a month' as a permanent zero rate."""
        return await run(
            "simulate_intervention",
            lambda who: tools.simulate_intervention(who, goal_id, changes),
        )

    @server.tool(annotations=_WRITE, title="Create goal")
    async def create_goal(
        intent: Annotated[str, Field(min_length=3, max_length=2000)],
        idempotency_key: Annotated[
            str | None, Field(default=None, min_length=8, max_length=128)
        ] = None,
    ) -> GoalCreationView:
        """Start PlayItOut's Goal Architect. Underspecified intents return questions.
        A measurable contract is not saved until continue_goal_creation confirms it.
        Uses model credits. Never invents a probability."""
        return await run(
            "create_goal",
            lambda who: tools.create_goal(who, intent, idempotency_key),
            write=True,
            inference=True,
        )

    @server.tool(annotations=_WRITE, title="Continue goal creation")
    async def continue_goal_creation(
        thread_id: Annotated[str, Field(max_length=64)],
        answers: dict[str, str] | None = None,
        confirmed: bool | None = None,
        cancelled: bool = False,
    ) -> GoalCreationView:
        """Continue a create_goal thread: answer clarification questions, confirm the
        contract, or cancel. Survives separate tool calls. Confirmation is required
        before a market is created."""
        return await run(
            "continue_goal_creation",
            lambda who: tools.continue_goal_creation(
                who, thread_id, answers, confirmed, cancelled
            ),
            write=True,
            inference=True,
        )

    @server.tool(annotations=_READ, title="Compare forecasts")
    async def compare_forecasts(
        goal_id: GoalId,
        as_of: Annotated[str | None, Field(default=None, max_length=40)] = None,
        relative: Annotated[
            str | None,
            Field(
                default=None,
                pattern=(
                    r"^(latest|previous|last_week|this_month|since_start|"
                    r"before_evidence|largest_increase|largest_drop)$"
                ),
            ),
        ] = None,
        evidence_id: Annotated[str | None, Field(default=None, max_length=64)] = None,
    ) -> ForecastCompare:
        """Compare published receipts. Use as_of (ISO-8601),
        relative=last_week|this_month|since_start|previous|before_evidence|
        largest_increase|largest_drop, or evidence_id. Delta is percentage points.
        Observation, ingestion and publication times stay separate. Missing history
        is reported; it is not interpolated."""
        return await run(
            "compare_forecasts",
            lambda who: tools.compare_forecasts(who, goal_id, as_of, relative, evidence_id),
        )

    @server.tool(annotations=_READ, title="Compare scenarios")
    async def compare_scenarios(
        goal_id: GoalId,
        scenarios: Annotated[list[dict[str, Any]], Field(min_length=1, max_length=5)],
        as_of: Annotated[str | None, Field(default=None, max_length=40)] = None,
        relative: Annotated[
            str | None,
            Field(
                default=None,
                pattern=r"^(latest|previous|last_week|this_month|since_start)$",
            ),
        ] = None,
        weighted: dict[str, Any] | None = None,
    ) -> ScenarioCompare:
        """Run one or more hypothetical What If scenarios without writing published
        history. Each scenario is {label, changes:[{metric,operation,value,unit}]}.
        Optional weighted={components:[{label,score,weight,known}]} computes exam
        arithmetic only when every weight is known; otherwise it asks a question.
        Unsupported causal claims stay NOT_PRICED."""
        return await run(
            "compare_scenarios",
            lambda who: tools.compare_scenarios(
                who, goal_id, scenarios, as_of, relative, weighted
            ),
        )

    @server.tool(annotations=_WRITE, title="Submit structured rows")
    async def submit_structured_rows(
        goal_id: GoalId,
        rows: Annotated[list[StructuredRow], Field(min_length=1, max_length=25)],
        idempotency_key: IdempotencyKey,
        source_category: SourceCategory,
        source_identifier: OptionalRef = None,
        supporting_reference: OptionalRef = None,
    ) -> SubmissionResult:
        """Commit up to 25 typed observations in one call. Preferred file-handoff
        path: agents should extract rows rather than forwarding Gmail attachments."""
        return await run(
            "submit_structured_rows",
            lambda who: tools.submit_structured_rows(
                who,
                goal_id=goal_id,
                rows=rows,
                idempotency_key=idempotency_key,
                source_category=source_category,
                source_identifier=source_identifier,
                supporting_reference=supporting_reference,
            ),
            write=True,
        )

    @server.tool(annotations=_WRITE, title="Submit table text")
    async def submit_table_text(
        goal_id: GoalId,
        filename: Annotated[str, Field(min_length=4, max_length=80)],
        text: Annotated[str, Field(min_length=3, max_length=20000)],
        mapping: dict[str, str],
        idempotency_key: IdempotencyKey,
        source_category: SourceCategory,
    ) -> SubmissionResult:
        """Ingest a small CSV/text table through the existing upload mapper.
        mapping needs value_column and usually metric, unit, observed_at_column,
        observation_kind. Does not fetch URLs."""
        return await run(
            "submit_table_text",
            lambda who: tools.submit_table_text(
                who,
                goal_id=goal_id,
                filename=filename,
                text=text,
                mapping=mapping,
                idempotency_key=idempotency_key,
                source_category=source_category,
            ),
            write=True,
        )

    @server.tool(annotations=_WRITE, title="Submit file bytes")
    async def submit_file_bytes(
        goal_id: GoalId,
        filename: Annotated[str, Field(min_length=4, max_length=80)],
        content_base64: Annotated[str, Field(min_length=8, max_length=56000)],
        mapping: dict[str, str],
        idempotency_key: IdempotencyKey,
        source_category: SourceCategory,
    ) -> SubmissionResult:
        """Optional bounded binary transfer (CSV/XLSX/PDF, decoded max 40 KB) that
        reuses the existing upload backend. Larger files are rejected; use
        submit_structured_rows. No URL fetching."""
        return await run(
            "submit_file_bytes",
            lambda who: tools.submit_file_bytes(
                who,
                goal_id=goal_id,
                filename=filename,
                content_base64=content_base64,
                mapping=mapping,
                idempotency_key=idempotency_key,
                source_category=source_category,
            ),
            write=True,
        )

    _CHART_META = {
        "ui": {"resourceUri": ODDS_UI_URI, "visibility": ["model", "app"]},
        "ui/resourceUri": ODDS_UI_URI,
    }

    @server.tool(
        annotations=_READ,
        title="Show odds chart",
        meta=_CHART_META,
    )
    async def show_odds_chart(
        goal_id: GoalId,
        range: Annotated[str, Field(pattern=r"^(1D|1W|1M|1Y|ALL)$")] = "ALL",
    ) -> OddsChartView:
        """Published forecast history for an interactive Odds Explorer. Hosts that
        implement MCP Apps (io.modelcontextprotocol/ui) should render
        ui://playitout/odds-explorer/v2. Other hosts should call get_odds_chart_image.
        Never invents points."""
        return await run(
            "show_odds_chart",
            lambda who: tools.show_odds_chart(who, goal_id, range),
        )

    @server.tool(annotations=_READ, title="Get odds chart image")
    async def get_odds_chart_image(
        goal_id: GoalId,
        range: Annotated[str, Field(pattern=r"^(1D|1W|1M|1Y|ALL)$")] = "ALL",
    ) -> CallToolResult:
        """Static PNG of published odds for hosts that cannot render MCP Apps.
        Owner-bound: requires a valid access token. No public URL is issued."""

        async def _image(who: Caller) -> CallToolResult:
            view, png = await tools.get_odds_chart_image(who, goal_id, range)
            payload = view.model_dump(mode="json")
            payload.update(
                {
                    "mime_type": "image/png",
                    "byte_size": len(png),
                    "static": True,
                    "public_url": None,
                    "message": (
                        "Static PNG. Interactive controls are not available in this payload."
                    ),
                }
            )
            return CallToolResult(
                content=[
                    TextContent(type="text", text=json.dumps(payload)),
                    ImageContent(
                        type="image",
                        data=base64.b64encode(png).decode("ascii"),
                        mime_type="image/png",
                    ),
                ],
                structured_content=payload,
            )

        return await run("get_odds_chart_image", _image)

    @server.tool(annotations=_READ, title="Search public markets")
    async def search_public_markets(
        query: Annotated[str | None, Field(default=None, max_length=80)] = None,
        limit: Annotated[int, Field(ge=1, le=25)] = 12,
    ) -> dict[str, Any]:
        """Search published PlayItOut markets. Returns public blueprint cards only."""
        return await run(
            "search_public_markets",
            lambda who: tools.search_public_markets(who, query, limit),
        )

    @server.tool(annotations=_READ, title="Get public market")
    async def get_public_market(goal_id: GoalId) -> dict[str, Any]:
        """Read one public market and its approved blueprint. Private markets 404."""
        return await run("get_public_market", lambda who: tools.get_public_market(who, goal_id))

    @server.tool(annotations=_READ, title="Get blueprint")
    async def get_blueprint(goal_id: GoalId) -> dict[str, Any]:
        """Return the reusable public blueprint for a published market."""
        return await run("get_blueprint", lambda who: tools.get_blueprint(who, goal_id))


def _advertise_ui_on_handshake(server: MCPServer) -> None:
    """Handshake-era initialize (2025-06-18) sieves `capabilities.extensions`.

    The official SDK still registers `io.modelcontextprotocol/ui` on the 2026
    extensions map. Handshake clients only see `experimental`, so the same
    settings are copied there. Tool `_meta.ui.resourceUri` is the actual
    MCP Apps linkage and does not depend on this advertisement.
    """
    inner = server._lowlevel_server
    original = inner.create_initialization_options

    def create_initialization_options(
        notification_options: Any = None,
        experimental_capabilities: dict[str, dict[str, Any]] | None = None,
        extensions: dict[str, dict[str, Any]] | None = None,
    ) -> Any:
        advertised = dict(extensions if extensions is not None else inner.extensions)
        experimental = dict(experimental_capabilities or {})
        experimental.setdefault(UI_EXTENSION_ID, advertised.get(UI_EXTENSION_ID, {}))
        return original(
            notification_options,
            experimental,
            advertised,
        )

    inner.create_initialization_options = create_initialization_options  # type: ignore[method-assign]
