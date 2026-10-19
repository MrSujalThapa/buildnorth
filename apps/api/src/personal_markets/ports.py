from datetime import datetime
from typing import Annotated, Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, Field, WithJsonSchema, field_validator

from personal_markets.goals.domain import GoalContract

GoalTypeName = Literal["deadline_event", "threshold", "continuous_target", "habit", "multi_outcome"]
CriticDecision = Literal["publish", "publish_with_limitations", "withhold"]
EvidenceClass = Literal[
    "causal",
    "quasi-experimental",
    "matched",
    "associative",
    "mechanistic",
    "assumption",
    "official_rule",
    "reference_rule",
]


class ClarificationQuestion(BaseModel):
    id: str
    question: str
    why_needed: str


# Strict structured output closes every object, so an open map can only be emitted
# as `{}`. Providers send known values as key/value pairs; the domain keeps a dict.
_KNOWN_STATE_WIRE_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"key": {"type": "string"}, "value": {"type": "string"}},
        "required": ["key", "value"],
        "additionalProperties": False,
    },
}


class GoalArchitectProposal(BaseModel):
    ready_to_commit: bool
    title: str = Field(min_length=3, max_length=200)
    goal_type: GoalTypeName
    success_metric: str
    success_operator: str
    success_target: str
    deadline: str
    state_dimensions: list[str]
    hours_per_week: float | None = None
    model_family_compatibility: str
    clarifications_required: list[ClarificationQuestion] = Field(default_factory=list)
    notes: str = ""
    success_unit: str | None = None
    research_required: bool = False
    research_questions: list[str] = Field(default_factory=list)
    primitive_kind: str | None = None
    primitives: list[dict[str, Any]] = Field(default_factory=list)
    current_state_known: Annotated[
        dict[str, str], WithJsonSchema(_KNOWN_STATE_WIRE_SCHEMA)
    ] = Field(default_factory=dict)
    missing_inputs: list[str] = Field(default_factory=list)

    @field_validator("current_state_known", mode="before")
    @classmethod
    def _known_state_pairs(cls, value: object) -> object:
        if isinstance(value, list):
            return {
                str(item["key"]): str(item["value"])
                for item in value
                if isinstance(item, dict) and item.get("key") is not None
            }
        return value


class EvidenceEventProposal(BaseModel):
    event_type: str
    domain: str
    metric: str
    numeric_value: float | None = Field(default=None, allow_inf_nan=False)
    categorical_value: str | None = None
    unit: str | None = None
    observed_at: str
    source_type: Literal["manual", "github", "csv", "mcp_sync", "upload", "personal_agent"]
    summary: str
    observation_kind: Literal["snapshot", "increment", "period", "event", "uncertain"] | None = None
    event_identity: str | None = None


class EvidenceAgentProposal(BaseModel):
    events: list[EvidenceEventProposal]
    ambiguities: list[ClarificationQuestion] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class ResearchClaim(BaseModel):
    claim: str
    source: str
    retrieved_at: str
    source_type: Literal["official", "frozen", "web", "dataset"]
    evidence_class: EvidenceClass
    supporting_quote: str = ""
    population: str = ""
    applicability: Literal["applicable", "mismatch", "unknown"] = "unknown"
    parameter: str | None = None
    value: float | None = None
    unit: str | None = None
    contradiction: str | None = None
    verification: Literal["candidate", "source_supported", "frozen_reference"] = "candidate"
    material_kind: Literal["snippet", "document_text", "frozen_reference"] = "snippet"
    source_role: Literal["primary", "commentary", "unknown"] = "unknown"


class ResearchArtifact(BaseModel):
    claims: list[ResearchClaim] = Field(default_factory=list)
    reference_class_candidates: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    status: Literal["sufficient", "insufficient_evidence", "not_required"] = "insufficient_evidence"
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)
    parameter_provenance: list[dict[str, Any]] = Field(default_factory=list)


class CriticArtifact(BaseModel):
    decision: CriticDecision
    issues: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    required_actions: list[str] = Field(default_factory=list)


EffectStrength = Literal["CALIBRATED", "ANCHORED", "EXPLORATORY", "NOT_PRICED"]
InterventionPricingStatus = Literal["PRICED", "NOT_PRICED", "ASSUMPTION_REQUIRED"]
SourceRelevance = Literal["recommended", "optional", "irrelevant"]


class InterventionMechanismStep(BaseModel):
    variable: str
    description: str


class InterventionStateChange(BaseModel):
    metric: str
    operation: Literal["set", "add", "subtract"]
    value: float = Field(allow_inf_nan=False)
    unit: str
    frequency: str | None = None
    scope: str = "goal_state"
    provenance: Literal["USER_ASSUMPTION", "REFERENCE", "FITTED", "EXPLORATION_ASSUMPTION"]
    strength: EffectStrength = "EXPLORATORY"


class InterventionAgentProposal(BaseModel):
    understood_action: str
    mechanism: list[InterventionMechanismStep] = Field(default_factory=list)
    changes: list[InterventionStateChange] = Field(default_factory=list)
    pricing_status: InterventionPricingStatus
    unsupported: list[str] = Field(default_factory=list)
    research_claims: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    notes: str = ""


class InterventionCriticArtifact(BaseModel):
    approved: bool
    pricing_status: InterventionPricingStatus
    validated_changes: list[InterventionStateChange] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class SourceResourceSelection(BaseModel):
    resource_id: str
    label: str
    rationale: str
    resource_type: str = "resource"
    why: str = ""
    goal_relevance: str = "medium"
    state_variables: list[str] = Field(default_factory=list)
    recommended: bool = False


class SourceRecommendation(BaseModel):
    plugin_id: str
    relevance: SourceRelevance
    rationale: str
    resources: list[SourceResourceSelection] = Field(default_factory=list)


class SourcePlannerProposal(BaseModel):
    goal_title: str
    goal_type: str
    state_dimensions: list[str]
    recommended: list[SourceRecommendation] = Field(default_factory=list)
    irrelevant: list[SourceRecommendation] = Field(default_factory=list)
    manual_fallback_note: str = ""


class PricingResult(BaseModel):
    priced: bool
    forecast_status: str
    raw_probability: float | None = Field(default=None, ge=0, le=1)
    calibrated_probability: float | None = Field(default=None, ge=0, le=1)
    model_version: str | None = None
    limitations: list[str] = Field(default_factory=list)
    receipt: dict[str, Any] = Field(default_factory=dict)


class WorkflowRequest(BaseModel):
    kind: Literal["create_goal", "add_evidence", "reprice"]
    intent: str | None = None
    goal_id: UUID | None = None
    evidence_text: str | None = None
    user_id: UUID | None = None
    thread_id: UUID | None = None
    github_login: str | None = None
    evidence_events: list[EvidenceEventProposal] | None = None
    mcp_records: list[dict[str, Any]] | None = None


class InterruptPayload(BaseModel):
    type: Literal["clarification", "confirm_contract", "confirm_evidence"]
    questions: list[ClarificationQuestion] = Field(default_factory=list)
    proposal: dict[str, Any] | None = None
    message: str


class WorkflowSnapshot(BaseModel):
    thread_id: UUID
    kind: str
    status: str
    current_step: str
    progress: list[str] = Field(default_factory=list)
    interrupt: InterruptPayload | None = None
    goal: GoalContract | None = None
    evidence: list[EvidenceEventProposal] = Field(default_factory=list)
    research: ResearchArtifact | None = None
    pricing: PricingResult | None = None
    critic: CriticArtifact | None = None
    agent_run_ids: dict[str, str] = Field(default_factory=dict)
    debug: dict[str, Any] = Field(default_factory=dict)


class ResumePayload(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)
    confirmed: bool | None = None
    cancelled: bool = False


class ToolDefinition(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
    description: str
    input_schema: dict[str, Any]


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class InferenceRequest(BaseModel):
    instructions: str
    input: dict[str, Any]
    output_schema: dict[str, Any]
    model: str | None = None
    fallback_models: list[str] = Field(default_factory=list)
    pool: Literal["high_volume", "premium"] = "high_volume"
    agent_name: str = "unknown"
    timeout_seconds: float | None = None
    user_id: UUID | None = None
    client_ip: str | None = None
    tools: list[ToolDefinition] = Field(default_factory=list)
    max_output_tokens: int | None = Field(default=None, ge=32, le=8192)


class InferenceResponse(BaseModel):
    structured_output: dict[str, Any]
    provider: str
    model: str
    usage: dict[str, int] = Field(default_factory=dict)
    request_id: str | None = None
    retries: int = 0
    latency_ms: int = 0
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    estimated_cost_usd: float | None = None
    billing_mode: Literal["hosted", "byok"] = "hosted"
    usage_reported: bool = True


class InferenceProvider(Protocol):
    async def complete_structured(self, request: InferenceRequest) -> InferenceResponse: ...

    async def complete_text(self, request: InferenceRequest) -> InferenceResponse: ...

    async def complete_tools(self, request: InferenceRequest) -> InferenceResponse: ...


class ResearchQuery(BaseModel):
    query: str
    as_of: datetime
    allowed_domains: list[str] = Field(default_factory=list)
    goal_type: str | None = None
    external_required: bool = False
    user_id: UUID | None = None


class ResearchResult(BaseModel):
    claims: list[dict[str, Any]]
    retrieved_at: datetime
    provenance: list[dict[str, str]]
    configured: bool = True
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)


class ResearchProvider(Protocol):
    async def search(self, query: ResearchQuery) -> ResearchResult: ...


class EvidenceBatch(BaseModel):
    records: list[dict[str, Any]]
    next_cursor: str | None = None


class EvidenceSource(Protocol):
    async def sync(self, cursor: str | None) -> EvidenceBatch: ...


class AgentWorkflow(Protocol):
    async def start(self, request: WorkflowRequest) -> WorkflowSnapshot: ...

    async def resume(self, thread_id: UUID, payload: ResumePayload) -> WorkflowSnapshot: ...

    async def snapshot(self, thread_id: UUID) -> WorkflowSnapshot: ...
