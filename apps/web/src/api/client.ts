import { currentAccessToken, type AccountView } from "../auth/session";
import { resolveApiBaseUrl } from "./baseUrl";

export type ForecastStatus = "CALIBRATED" | "ANCHORED" | "EXPLORATORY";

export type InferencePreference = {
  mode: "hosted" | "byok";
  provider: "openai" | "anthropic";
  model: string | null;
};
export type CredentialMetadata = {
  provider: "openai" | "anthropic";
  status: "validated" | "invalid";
  masked_suffix: string;
  version: string;
  validated_at: string;
};
export type InferenceModelOption = {
  provider: string;
  model: string;
  structured: boolean;
  tools: boolean;
  display_name?: string | null;
  pricing_available?: boolean;
  compatibility?: string;
  source?: string;
  pricing_basis?: string;
};
export type InferenceSettings = {
  preference: InferencePreference;
  credentials: CredentialMetadata[];
  models: InferenceModelOption[];
  discovered_models?: Record<string, InferenceModelOption[]>;
  recommended_model?: string | null;
  hosted_provider: string;
  hosted_configured: boolean;
  hosted_model: string | null;
  byok_usage: { calls: number; input_tokens: number; output_tokens: number; estimated_cost_usd: number };
};

export type InvitationRecord = {
  invitation_id: string;
  email: string | null;
  note: string;
  kind: "email" | "shared";
  max_redemptions: number;
  redemption_count: number;
  hosted_quota_usd: number;
  hosted_quota_tokens: number;
  expires_at: string;
  revoked_at: string | null;
  redeemed_at: string | null;
  token?: string | null;
};

export type StrategyDecision = "pending" | "accepted" | "declined" | "ignored";

export type StrategyTrial = {
  recommendation_id: string;
  strategy_key: string;
  action: string;
  recommended_at: string;
  decision: StrategyDecision;
  expected?: { metric: string; unit: string; direction: string; target?: number | null };
  next_step?: string;
  why_now?: string;
  outcome_status?: string;
};

export type StrategyLearningContext = {
  goal_id: string;
  as_of: string;
  past_trials: StrategyTrial[];
  note: string;
};

export type StrategyRecommendation = StrategyTrial & {
  why_now: string;
  next_step: string;
  evidence_to_collect?: string;
};

export interface Goal {
  goal_id: string;
  title: string;
  goal_type: "deadline_event" | "threshold" | "continuous_target" | "habit" | "multi_outcome";
  deadline: string;
  forecast_status: ForecastStatus;
  state_dimensions: string[];
  success_definition?: Record<string, unknown>;
  resource_constraints?: { hours_per_week?: number; budget_amount?: number; budget_currency?: string };
  model_requirements?: Record<string, unknown>;
}

export interface WhatIfAssumption {
  id?: string;
  name: string;
  description?: string;
  value: number;
  minimum: number;
  maximum: number;
  step: number;
  source: "FITTED" | "REFERENCE" | "USER_ASSUMPTION" | "EXPLORATION_ASSUMPTION";
  unit: string;
  provenance?: string;
  editable?: boolean;
  scope?: string;
  model_family?: string;
  version?: string;
  timestamp?: string;
}

export interface WhatIfResult {
  priced: boolean;
  status: string;
  message: string | null;
  baseline_probability: number | null;
  scenario_probability: number | null;
  conditional_on_execution_probability: number | null;
  execution_probability: number | null;
  expected_uplift_pp: number | null;
  uplift_interval_pp: [number, number] | null;
  p_uplift_positive: number | null;
  outcome_quantiles: Record<string, number>;
  fan: { period: number; p10: number; p50: number; p90: number }[];
  distribution_bins: { lower: number; upper: number; mass: number }[];
  assumptions: WhatIfAssumption[];
  opportunity_costs: string[];
  resource_usage?: { hours_per_week: number; money_per_month: number; within_budget: boolean; over_budget_notes: string[] } | null;
  resource_budget?: { hours_per_week: number; money_per_month: number } | null;
  resource_feasible?: boolean;
  diagnostics: { n_draws: number; seed: number; converged: boolean; achieved_mc_error: number; duration_ms: number } | null;
  sensitivity: {
    assumption_id: string;
    label: string;
    baseline_value: number;
    lower_value: number;
    upper_value: number;
    probability_at_lower: number;
    probability_at_baseline: number;
    probability_at_upper: number;
    swing: number;
    direction: string;
    assumption: string;
    probability_swing_pp: number;
    lower_probability: number;
    upper_probability: number;
  }[];
  fragility_pp: number | null;
  run_id: string | null;
  persisted: boolean;
  history_snapshot_created: boolean;
  receipt: Record<string, unknown>;
  llm_calls: number;
  total_latency_ms: number | null;
  execution_breakdown?: {
    current_probability: number;
    conditional_on_full_execution: number;
    follow_through_probability: number;
    execution_adjusted_probability: number;
    interval?: number[] | null;
    source?: string;
  } | null;
  behavior_profile?: BehaviorProfile | null;
}

export interface BehaviorDimension {
  key: string;
  label: string;
  value: number | null;
  display_percent: number | null;
  limited_evidence: boolean;
  confidence: string;
  provenance: {
    comparable_commitments: number;
    completed: number;
    recency_weighted_completion?: number | null;
    evidence_window_days?: number | null;
    sources: string[];
    n_eff: number;
    formula: string;
    details: string[];
  };
}

export interface BehaviorProfile {
  estimator_version: string;
  execution: {
    probability: number;
    n_eff: number;
    confidence: string;
    source: string;
    usable: boolean;
    notes: string[];
  };
  dimensions: BehaviorDimension[];
  disclaimer: string;
  evidence_sufficiency: string;
  n_raw: number;
  n_eff: number;
}

export interface TargetSearchResult {
  target_probability: number;
  current_probability: number;
  gap_pp: number;
  feasible: boolean;
  message: string;
  paths: { label: string; action_ids: string[]; resulting_probability: number; resource_cost: { hours_per_week: number; money: number; energy: number }; fragility_pp: number | null; valid_because: string; assumptions?: WhatIfAssumption[] }[];
  search_method: string;
  run_id: string | null;
  receipt: Record<string, unknown>;
}

export interface ActionFrontierResult {
  points: { id: string; label: string; resource_cost: number; expected_uplift_pp: number; dominated: boolean; action_ids: string[]; opportunity_costs: string[]; provenance: string[] }[];
  frontier_ids: string[];
  selected_id: string | null;
}

export interface ScenarioDistribution {
  priced: boolean;
  message: string | null;
  outcomes: { label: string; probability: number | null; downside: boolean; median: number | null; p10: number | null; p90: number | null }[];
  other_probability: number;
  evidence_basis: string[];
  model_version: string;
  run_id: string | null;
  receipt?: Record<string, unknown>;
}

export interface PathComparisonResult {
  paths: { id: string; label: string; primary_goal_probability: number | null; expected_outcome: number | null; median: number | null; p10: number | null; p90: number | null; downside_probability: number | null; fragility_pp: number | null; resource_cost: { hours_per_week: number; money: number; energy: number }; execution_probability: number | null; model_status: string }[];
  model_family: string;
  model_version: string;
  seed: number;
  run_id: string | null;
}

export interface ParsedInterventionChange {
  metric: string;
  operation: string;
  value: number;
  unit: string;
  frequency: string | null;
  scope: string;
  provenance: string;
}

export interface ParseDecisionResult {
  raw_text: string;
  decision: { action: string; alternative: string | null; timing: string; constraints: string[] } | null;
  scenario_labels: string[];
  unsupported: string[];
  /** Quantities stated in the text, read deterministically and checked against the model. */
  changes?: ParsedInterventionChange[];
}

export interface StrategyInsight {
  title: string;
  description: string;
  why_it_might_help: string;
  why_this_fits: string;
  next_step: string;
  evidence_to_collect: string;
  constraints?: string;
  modeled_metric?: string | null;
  model_status: "MODELED" | "UNPRICED" | "NEEDS_DATA";
  grounded_facts?: string[];
  assumptions?: string[];
  sources?: string[];
}

export interface ParseInterventionResult {
  raw_text: string;
  changes: ParsedInterventionChange[];
  unsupported: string[];
  effect_assigned: boolean;
  understood_action?: string;
  mechanism?: { variable: string; description: string }[];
  pricing_status?: string;
  agent_run_id?: string | null;
  limitations?: string[];
  research_claims?: string[];
  request_kind?: string;
  confirmation_needed?: boolean;
  insights?: StrategyInsight[];
  consumer_summary?: string;
}

export interface CourseGradeComponent {
  label: string;
  score: number | null;
  weight: number;
  known: boolean;
}

export interface CourseGradeRequest {
  components: CourseGradeComponent[];
  target?: number | null;
  remaining_score?: number | null;
  scenarios?: number[];
}

export interface CourseGradeResult {
  status: string;
  average: number | null;
  known_contribution: number | null;
  known_weight: number | null;
  remaining_weight: number | null;
  required_remaining: number | null;
  required_is_uniform: boolean;
  unattainable: boolean;
  already_met: boolean;
  scenarios: { label: string; remaining_score: number; average: number; meets_target: boolean | null }[];
  questions: string[];
  missing: string[];
  message: string;
  arithmetic_only: boolean;
  writes_evidence: boolean;
}

export interface SourcePreviewRecord {
  kind: "measurement" | "activity" | "message" | "document" | "record";
  title: string;
  subtitle?: string | null;
  timestamp?: string | null;
  metric?: string | null;
  numeric_value?: number | null;
  unit?: string | null;
  text?: string | null;
  actor?: string | null;
  metrics?: { label: string; value: number; unit?: string | null }[];
  cells?: string[];
}

export interface SourcePreview {
  resource_title: string;
  resource_type: string;
  tool_name: string;
  arguments: Record<string, string>;
  fields: { key: string; label: string; role: string }[];
  columns?: string[];
  measurements: { id: string; label: string; detail: string; unit?: string | null; ambiguous: boolean }[];
  records: SourcePreviewRecord[];
  notice?: string | null;
  validation_status: "unverified";
  promotes_to_verified_outcome: false;
  error?: string | null;
}

export interface SourceResourceSelection {
  resource_id: string;
  label: string;
  rationale: string;
  resource_type?: string;
  why?: string;
  goal_relevance?: string;
  state_variables?: string[];
  recommended?: boolean;
}

export interface SourceRecommendation {
  plugin_id: string;
  relevance: string;
  rationale: string;
  resources: SourceResourceSelection[];
}

export interface SourcePlannerProposal {
  goal_title: string;
  goal_type: string;
  state_dimensions: string[];
  recommended: SourceRecommendation[];
  irrelevant: SourceRecommendation[];
  manual_fallback_note?: string;
}

export interface PluginCatalogResponse {
  items: PluginView[];
  next_cursor: string | null;
  total_items: number | null;
  provider_status?: "available" | "unavailable" | "error";
  provider_message?: string | null;
}

export interface CollectionProgress {
  label: string;
  value: number | null;
  available: number;
  total: number;
  incomplete: boolean;
  methodology: string;
  notes: string[];
}

export interface CollectionSeries {
  goal_id: string;
  title: string;
  color: string;
  points: { timestamp: string | number | null; value: number }[];
  withheld: boolean;
}

export interface CollectionView {
  collection: {
    collection_id: string;
    owner_id: string;
    name: string;
    description: string;
    icon: string | null;
    color: string | null;
    position: number;
    goal_ids: string[];
  };
  progress: CollectionProgress;
  series: CollectionSeries[];
  portfolio_odds: number | null;
  change_pp: number | null;
  priced_goals: number;
  total_goals: number;
  portfolio_methodology: string;
}

export interface GoalsDashboard {
  goals: Goal[];
  histories: Record<string, MarketHistoryPoint[]>;
  creation_states?: Record<string, { status: string; critic_decision: string | null }>;
  collections?: CollectionView[];
  social?: Record<string, OwnerMarketSocial>;
}

export type MarketVisibility = "private" | "public";

export interface PublicCreator {
  user_id: string;
  handle: string;
  username: string | null;
  display_name: string | null;
  bio: string | null;
  has_photo: boolean;
  demo_persona?: boolean;
}

export interface PublicHistoryPoint {
  created_at: string;
  probability: number;
}

export interface PublicForecastState {
  status: "published" | "withheld" | "unpublished" | "exploratory";
  category?: string | null;
}

export interface PublicBlueprint {
  title: string;
  description: string;
  category: string;
  deadline?: string | null;
  success_criteria: Record<string, unknown>;
  milestones: unknown[];
  strategies: string[];
  evidence_types: string[];
  suggested_integrations: string[];
  model_configuration: Record<string, unknown>;
  forecast: PublicForecastState;
}

export interface PublicMarketCard {
  goal_id: string;
  title: string;
  description: string;
  category: string;
  visibility: MarketVisibility;
  creator: PublicCreator;
  star_count: number;
  fork_count: number;
  starred: boolean;
  published_at: string | null;
  updated_at: string | null;
  latest_probability: number | null;
  forecast: PublicForecastState;
  history: PublicHistoryPoint[];
  fork: {
    source_goal_id: string;
    source_user_id: string;
    source_handle: string | null;
    source_title: string | null;
    source_public: boolean;
    forked_at: string;
  } | null;
}

export interface PublicMarketDetail extends PublicMarketCard {
  blueprint: PublicBlueprint;
  share_path: string;
}

export interface OwnerMarketSocial {
  goal_id: string;
  visibility: MarketVisibility;
  published_at: string | null;
  star_count: number;
  fork_count: number;
  starred: boolean;
  public_preview?: PublicBlueprint | null;
}

export interface PublicProfile {
  creator: PublicCreator;
  follower_count: number;
  following_count: number;
  following: boolean;
  is_self: boolean;
  market_count: number;
  contribution_total: number;
  activity: { day: string; count: number }[];
}

export type TraitForecastUse = "execution_probability" | "exploratory";

export interface TraitOption {
  id: string;
  name: string;
  description: string;
  measurement: string;
  evidence: string[];
  custom: boolean;
  forecast_use: TraitForecastUse;
  metric?: string;
}

export interface TraitEstimate {
  id: string;
  name: string;
  description: string;
  measurement: string;
  evidence: string[];
  custom: boolean;
  forecast_use: TraitForecastUse;
  value: number | null;
  interval: [number, number] | null;
  n_eff: number;
  observations: number;
  confidence: "insufficient" | "low" | "moderate" | "high";
  previous_value: number | null;
  sources: string[];
  window_days: number | null;
}

export interface TraitSeries {
  id: string;
  label: string;
  values: Record<string, number | null>;
}

export interface TraitProfile {
  estimator_version: string;
  as_of: string;
  traits: TraitEstimate[];
  series: TraitSeries[];
  trial_count: number;
  evidence_count: number;
}

export interface ProfilePayload {
  account: AccountView;
  goal_count: number;
  collection_count: number;
  traits: TraitProfile;
  radar: ParameterProfile;
  selected_parameters: string[];
  available_parameters: TraitOption[];
  privacy: string;
}

export interface ParameterEstimate {
  id: string;
  name: string;
  metric: string;
  unit: string;
  window_days: number;
  aggregation: "latest_period" | "sum_increments";
  normalization: string;
  raw_value: number | null;
  value: number | null;
  observation_count: number;
  source_types: string[];
  evidence_ids: string[];
  last_observed_at?: string | null;
  status: "measured" | "insufficient";
}

export interface ParameterProfile {
  version: string;
  as_of: string;
  parameters: ParameterEstimate[];
  evidence_count: number;
  synthetic: boolean;
}

export interface PluginConnectResponse {
  plugin_id: string;
  connection_id: string;
  status: string;
  auth_url?: string;
  connected_account_id?: string;
  account_label?: string;
}

export interface SourceRecipeRecord {
  goal_id: string;
  plugin_id: string;
  label: string;
  approved: boolean;
  steps: { capability_id: string; tool_name?: string | null; resource_uri?: string | null; arguments: Record<string, unknown> }[];
}

export interface SourceWatchRecord {
  id: string;
  goal_id: string;
  plugin_id: string;
  resource_id: string;
  scope: "resource" | "parent";
  status: "active" | "paused" | "revoked";
  last_success_at: string | null;
  last_error: string | null;
}

export interface GoalSyncJob {
  id: string;
  owner_id: string;
  goal_id: string;
  status: "queued" | "fetching_sources" | "processing_evidence" | "updating_forecast" | "completed" | "failed" | "timed_out";
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  receipt: Record<string, unknown>;
  error: string | null;
}

export interface MissingStateInput {
  key: string;
  label: string;
  unit: string;
  why: string;
  example?: string | null;
  suggested_sources: string[];
}

export interface SatisfiedStateInput {
  key: string;
  label: string;
  value: number;
  source: string;
  detail: string;
}

export interface Priceability {
  status: "PRICED" | "ASSUMPTION_REQUIRED" | "NOT_PRICED";
  model_family: string;
  headline: string;
  reason?: string | null;
  missing: MissingStateInput[];
  satisfied: SatisfiedStateInput[];
}

export interface WhatIfBaselineState {
  goal_id: string;
  priced: boolean;
  status: string;
  message?: string | null;
  current_value?: number | null;
  target_value?: number | null;
  target_unit?: string | null;
  periods?: number | null;
  direction: "at_least" | "at_most";
  current_probability?: number | null;
  published_probability?: number | null;
  published_model_version?: string | null;
  published_evidence_watermark?: string | null;
  assumptions: WhatIfAssumption[];
  default_intervention?: Record<string, unknown> | null;
  model_family: string;
  model_version: string;
  evidence_count: number;
  evidence_watermark: string;
  reference_versions: string[];
  domain_state: Record<string, unknown>;
  resource_constraints: { hours_per_week: number; money: number; energy: number };
  resource_budget: { hours_per_week: number; money_per_month: number };
  limitations: string[];
  priceability?: Priceability | null;
  config: { seed: number; minimum_draws: number; batch_draws: number; maximum_draws: number; probability_se_tolerance?: number };
  compare_candidates: {
    id: string;
    title: string;
    intervention: Record<string, unknown>;
    provenance: string[];
  }[];
}

export interface WhatIfExploration {
  id: string;
  goal_id: string;
  run_kind: string;
  status: string;
  created_at?: string | null;
  intervention_title?: string | null;
  baseline_probability?: number | null;
  scenario_probability?: number | null;
  conditional_on_execution_probability?: number | null;
  execution_probability?: number | null;
  expected_uplift_pp?: number | null;
}

export interface MarketHistoryPoint {
  id: string;
  probability: number;
  forecast_status: string;
  evidence_watermark: string;
  model_family: string;
  model_version: string;
  assumption_hash: string;
  simulation_run_id: string | null;
  source_kind: "published_forecast" | "synthetic_demo";
  created_at: string | null;
}

export interface PluginView {
  definition: { id: string; name: string; description: string; category: string; provider_type: string; logo_url?: string | null; capabilities: { id: string; label: string; operation: string }[]; used_for: string[]; evidence_readiness?: string; readiness_detail?: string };
  connection: { plugin_id: string; status: "connected" | "not_connected" | "pending_auth" | "syncing" | "error" | "unavailable"; connected_at: string | null; last_sync_at: string | null; permissions: string[]; account_metadata: Record<string, string>; error: string | null };
}

export interface Health {
  status: string;
  service: string;
  version: string;
  database?: string;
}

export interface ClarificationQuestion {
  id: string;
  question: string;
  why_needed: string;
}

export interface InterruptPayload {
  type: "clarification" | "confirm_contract" | "confirm_evidence";
  questions: ClarificationQuestion[];
  proposal: Record<string, unknown> | null;
  message: string;
}

export interface EvidenceEvent {
  event_type: string;
  domain: string;
  metric: string;
  numeric_value: number | null;
  categorical_value: string | null;
  unit: string | null;
  observed_at: string;
  source_type: "manual" | "github" | "csv" | "upload" | "mcp_sync" | "personal_agent";
  summary: string;
}

export type McpScope = {
  scope: string;
  label: string;
  description: string;
  writes: boolean;
  spends_credits: boolean;
};

export type McpStatus = {
  enabled: boolean;
  endpoint: string;
  transport: string;
  auth: string;
  dynamic_client_registration: boolean;
  scopes: McpScope[];
  default_scopes: string[];
  public_https: boolean;
  tools: string[];
};

export type McpConnection = {
  connection_id: string;
  client_id: string;
  client_name: string;
  scopes: McpScope[];
  status: "active" | "revoked";
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
};

export type McpAuthorizationRequest = {
  request_id: string;
  client_id: string;
  client_name: string;
  client_uri: string | null;
  redirect_host: string;
  redirect_scheme: string;
  scopes: McpScope[];
  resource: string;
  expires_at: string;
  verified_client: boolean;
  warnings: string[];
};

export type UploadRecord = {
  upload_id: string;
  goal_id: string;
  filename: string;
  content_type: string;
  byte_size: number;
  sha256: string;
  status: string;
  preview: {
    kind?: string;
    columns?: string[];
    sample_rows?: Record<string, string>[];
    row_count?: number;
    text_excerpt?: string;
    ambiguous?: boolean;
    note?: string;
  };
  mapping: Record<string, string> | null;
  created_at: string;
};

export interface WorkflowSnapshot {
  thread_id: string;
  kind: string;
  status: string;
  current_step: string;
  progress: string[];
  interrupt: InterruptPayload | null;
  goal: Goal | null;
  evidence: EvidenceEvent[];
  research: { claims: { claim: string; source: string; evidence_class: string }[]; limitations: string[] } | null;
  pricing: {
    priced: boolean;
    forecast_status: string;
    raw_probability: number | null;
    calibrated_probability: number | null;
    limitations: string[];
    receipt: Record<string, unknown>;
  } | null;
  critic: {
    decision: "publish" | "publish_with_limitations" | "withhold";
    issues: string[];
    limitations: string[];
    required_actions: string[];
  } | null;
  agent_run_ids: Record<string, string>;
  debug: Record<string, unknown>;
}

const ASYNC_JSON_HEADERS = { "Content-Type": "application/json", Prefer: "respond-async" };

async function watchThread(snapshot: WorkflowSnapshot, signal?: AbortSignal): Promise<WorkflowSnapshot> {
  let current = snapshot;
  const deadline = Date.now() + 120_000;
  while (current.status === "running" && Date.now() < deadline) {
    await new Promise((resolve) => window.setTimeout(resolve, 400));
    current = await request<WorkflowSnapshot>(`/api/v1/agent/threads/${current.thread_id}`, undefined, signal);
  }
  return current;
}

async function request<T>(
  path: string, init?: RequestInit, signal?: AbortSignal, notFoundValue?: T,
): Promise<T> {
  const token = await currentAccessToken();
  const baseUrl = resolveApiBaseUrl(import.meta.env.VITE_API_BASE_URL, window.location);
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    signal,
    headers: {
      Accept: "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
  });
  if (response.status === 404 && notFoundValue !== undefined) return notFoundValue;
  if (!response.ok) {
    let detail = `status ${response.status}`;
    try {
      const body = (await response.json()) as { error?: { message?: string } };
      if (body.error?.message) detail = body.error.message;
    } catch {
      // ignore parse errors
    }
    throw new Error(`API request failed (${detail})`);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function profilePhoto(signal?: AbortSignal): Promise<Blob | null> {
  const token = await currentAccessToken();
  const baseUrl = resolveApiBaseUrl(import.meta.env.VITE_API_BASE_URL, window.location);
  const response = await fetch(`${baseUrl}/api/v1/profile/photo`, {
    signal,
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error("Could not load profile photo");
  return response.blob();
}

export const api = {
  inferenceSettings: (signal?: AbortSignal) =>
    request<InferenceSettings>("/api/v1/settings/inference", undefined, signal),
  saveInferencePreference: (body: InferencePreference) =>
    request<InferenceSettings>("/api/v1/settings/inference", {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }),
  saveProviderKey: (provider: InferencePreference["provider"], apiKey: string) =>
    request<CredentialMetadata>(`/api/v1/settings/inference/credentials/${provider}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: apiKey }),
    }),
  validateProviderKey: (provider: InferencePreference["provider"]) =>
    request<CredentialMetadata>(`/api/v1/settings/inference/credentials/${provider}/validate`, { method: "POST" }),
  deleteProviderKey: (provider: InferencePreference["provider"]) =>
    request<void>(`/api/v1/settings/inference/credentials/${provider}`, { method: "DELETE" }),
  me: (signal?: AbortSignal) => request<AccountView>("/api/v1/me", undefined, signal),
  redeemInvite: (token: string) =>
    request<AccountView>("/api/v1/invites/redeem", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    }),
  createInvite: (body: {
    email?: string;
    note?: string;
    ttl_hours?: number;
    max_redemptions?: number;
  }) =>
    request<InvitationRecord>("/api/v1/admin/invites", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  listInvites: (signal?: AbortSignal) => request<InvitationRecord[]>("/api/v1/admin/invites", undefined, signal),
  revokeInvite: (invitationId: string) =>
    request<InvitationRecord>(`/api/v1/admin/invites/${invitationId}/revoke`, { method: "POST" }),
  workspaceSeedStatus: (signal?: AbortSignal) =>
    request<{ seed_version: string; seeded: boolean; records: Record<string, number> }>(
      "/api/v1/workspace-seed",
      undefined,
      signal,
    ),
  workspaceSeed: () =>
    request<{ seed_version: string; goals: { key: string; goal_id: string; status: string }[] }>(
      "/api/v1/workspace-seed",
      { method: "POST" },
    ),
  mcpStatus: (signal?: AbortSignal) => request<McpStatus>("/api/v1/mcp/status", undefined, signal),
  mcpConnections: (signal?: AbortSignal) =>
    request<McpConnection[]>("/api/v1/mcp/connections", undefined, signal),
  revokeMcpConnection: (connectionId: string) =>
    request<McpConnection>(`/api/v1/mcp/connections/${encodeURIComponent(connectionId)}`, { method: "DELETE" }),
  mcpAuthorizationRequest: (requestId: string, signal?: AbortSignal) =>
    request<McpAuthorizationRequest>(
      `/api/v1/mcp/authorization-requests/${encodeURIComponent(requestId)}`, undefined, signal,
    ),
  decideMcpAuthorization: (requestId: string, body: { approve: boolean; scopes?: string[] }) =>
    request<{ redirect_url: string }>(
      `/api/v1/mcp/authorization-requests/${encodeURIComponent(requestId)}/decision`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
    ),
  health: (signal?: AbortSignal) => request<Health>("/health", undefined, signal),
  goals: (signal?: AbortSignal) => request<Goal[]>("/api/v1/goals", undefined, signal),
  goalsDashboard: (signal?: AbortSignal) =>
    request<GoalsDashboard>("/api/v1/goals/dashboard", undefined, signal),
  goal: (goalId: string, signal?: AbortSignal) => request<Goal>(`/api/v1/goals/${goalId}`, undefined, signal),
  archiveGoal: (goalId: string) =>
    request<{ status: string }>(`/api/v1/goals/${goalId}`, { method: "DELETE" }),
  archiveGoals: (goalIds: string[]) =>
    request<{ archived: number; skipped: number }>("/api/v1/goals/archive", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ goal_ids: goalIds }),
    }),
  restoreGoal: (goalId: string) =>
    request<{ status: string }>(`/api/v1/goals/${goalId}/restore`, { method: "POST" }),
  collections: (signal?: AbortSignal) => request<CollectionView[]>("/api/v1/collections", undefined, signal),
  createCollection: (body: { name: string; description?: string; goal_ids?: string[] }) =>
    request<CollectionView>("/api/v1/collections", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  collection: (collectionId: string, signal?: AbortSignal) =>
    request<CollectionView>(`/api/v1/collections/${collectionId}`, undefined, signal),
  patchCollection: (collectionId: string, body: Record<string, unknown>) =>
    request<CollectionView>(`/api/v1/collections/${collectionId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteCollection: (collectionId: string) =>
    request<{ status: string }>(`/api/v1/collections/${collectionId}`, { method: "DELETE" }),
  addGoalsToCollection: (collectionId: string, goalIds: string[]) =>
    request<CollectionView>(`/api/v1/collections/${collectionId}/goals`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ goal_ids: goalIds }),
    }),
  publicMarkets: (params?: { q?: string; category?: string; sort?: string; limit?: number; offset?: number }, signal?: AbortSignal) => {
    const search = new URLSearchParams();
    if (params?.q) search.set("q", params.q);
    if (params?.category) search.set("category", params.category);
    if (params?.sort) search.set("sort", params.sort);
    if (params?.limit != null) search.set("limit", String(params.limit));
    if (params?.offset != null) search.set("offset", String(params.offset));
    const suffix = search.toString() ? `?${search}` : "";
    return request<{ items: PublicMarketCard[]; total: number; limit: number; offset: number }>(`/api/v1/public/markets${suffix}`, undefined, signal);
  },
  publicMarket: (goalId: string, signal?: AbortSignal) =>
    request<PublicMarketDetail>(`/api/v1/public/markets/${goalId}`, undefined, signal),
  publicProfile: (handle: string, signal?: AbortSignal) =>
    request<PublicProfile>(`/api/v1/public/profiles/${encodeURIComponent(handle)}`, undefined, signal),
  publicProfileMarkets: (handle: string, params?: { q?: string; visibility?: string }, signal?: AbortSignal) => {
    const search = new URLSearchParams();
    if (params?.q) search.set("q", params.q);
    if (params?.visibility) search.set("visibility", params.visibility);
    const suffix = search.toString() ? `?${search}` : "";
    return request<{ items: PublicMarketCard[] }>(
      `/api/v1/public/profiles/${encodeURIComponent(handle)}/markets${suffix}`,
      undefined,
      signal,
    );
  },
  publicProfileStars: (handle: string, signal?: AbortSignal) =>
    request<{ items: PublicMarketCard[] }>(
      `/api/v1/public/profiles/${encodeURIComponent(handle)}/stars`,
      undefined,
      signal,
    ),
  publicFollowGraph: (handle: string, kind: "followers" | "following", signal?: AbortSignal) =>
    request<{ items: { creator: PublicCreator; created_at: string }[] }>(
      `/api/v1/public/profiles/${encodeURIComponent(handle)}/${kind}`,
      undefined,
      signal,
    ),
  publicCreators: (signal?: AbortSignal) =>
    request<{ items: PublicCreator[] }>("/api/v1/public/creators", undefined, signal),
  publicPhotoUrl: (handle: string) => {
    const baseUrl = resolveApiBaseUrl(import.meta.env.VITE_API_BASE_URL, window.location);
    return `${baseUrl}/api/v1/public/profiles/${encodeURIComponent(handle)}/photo`;
  },
  marketSocial: (goalId: string, signal?: AbortSignal) =>
    request<OwnerMarketSocial>(`/api/v1/social/markets/${goalId}`, undefined, signal),
  setMarketVisibility: (goalId: string, visibility: MarketVisibility) =>
    request<OwnerMarketSocial>(`/api/v1/social/markets/${goalId}/visibility`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ visibility }),
    }),
  starMarket: (goalId: string) =>
    request<{ starred: boolean; star_count: number }>(`/api/v1/social/markets/${goalId}/star`, { method: "POST" }),
  unstarMarket: (goalId: string) =>
    request<{ starred: boolean; star_count: number }>(`/api/v1/social/markets/${goalId}/star`, { method: "DELETE" }),
  forkMarket: (goalId: string, body: { title?: string; deadline?: string; idempotency_key?: string }) =>
    request<{ goal_id: string; created: boolean; visibility: string; forked_from: string }>(
      `/api/v1/social/markets/${goalId}/fork`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
    ),
  shareMarket: (goalId: string) =>
    request<{ shareable: boolean; url?: string; title?: string; reason?: string }>(
      `/api/v1/social/markets/${goalId}/share`,
    ),
  followProfile: (handle: string) =>
    request<{ following: boolean; follower_count: number }>(
      `/api/v1/social/profiles/${encodeURIComponent(handle)}/follow`,
      { method: "POST" },
    ),
  unfollowProfile: (handle: string) =>
    request<{ following: boolean; follower_count: number }>(
      `/api/v1/social/profiles/${encodeURIComponent(handle)}/follow`,
      { method: "DELETE" },
    ),
  profile: (signal?: AbortSignal) => request<ProfilePayload>("/api/v1/profile", undefined, signal),
  profilePhoto,
  uploadProfilePhoto: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<{ status: string }>("/api/v1/profile/photo", { method: "PUT", body });
  },
  removeProfilePhoto: () => request<{ status: string }>("/api/v1/profile/photo", { method: "DELETE" }),
  patchProfile: (body: {
    display_name?: string;
    username?: string;
    bio?: string;
    avatar_value?: string;
    parameter_ids?: string[];
    custom_parameters?: { name: string; description: string }[];
  }) =>
    request<AccountView>("/api/v1/profile", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  evidence: (goalId: string, signal?: AbortSignal) =>
    request<EvidenceEvent[]>(`/api/v1/goals/${goalId}/evidence`, undefined, signal),
  startThread: async (body: { kind: string; intent?: string; goal_id?: string; evidence_text?: string; github_login?: string }) =>
    watchThread(
      await request<WorkflowSnapshot>("/api/v1/agent/threads", {
        method: "POST",
        headers: ASYNC_JSON_HEADERS,
        body: JSON.stringify(body),
      }),
    ),
  startThreadAsync: (body: { kind: string; intent?: string; goal_id?: string; evidence_text?: string; github_login?: string }) =>
    request<WorkflowSnapshot>("/api/v1/agent/threads", {
      method: "POST", headers: ASYNC_JSON_HEADERS, body: JSON.stringify(body),
    }),
  getThread: (threadId: string, signal?: AbortSignal) =>
    request<WorkflowSnapshot>(`/api/v1/agent/threads/${threadId}`, undefined, signal),
  goalEvidenceContinuation: (goalId: string, signal?: AbortSignal) =>
    request<WorkflowSnapshot | null>(
      `/api/v1/goals/${goalId}/evidence/continuation`, undefined, signal, null,
    ),
  retryGoalEvidence: (threadId: string) =>
    request<WorkflowSnapshot>(`/api/v1/agent/threads/${threadId}/evidence/retry`, { method: "POST" }),
  resumeThread: async (threadId: string, body: { answers?: Record<string, string>; confirmed?: boolean; cancelled?: boolean }) =>
    watchThread(
      await request<WorkflowSnapshot>(`/api/v1/agent/threads/${threadId}/resume`, {
        method: "POST",
        headers: ASYNC_JSON_HEADERS,
        body: JSON.stringify(body),
      }),
    ),
  resumeThreadAsync: (threadId: string, body: { answers?: Record<string, string>; confirmed?: boolean; cancelled?: boolean }) =>
    request<WorkflowSnapshot>(`/api/v1/agent/threads/${threadId}/resume`, {
      method: "POST", headers: ASYNC_JSON_HEADERS, body: JSON.stringify(body),
    }),
  addManualState: (
    goalId: string,
    entries: { key: string; label: string; value: number; unit: string }[],
  ) =>
    request<{
      events: EvidenceEvent[];
      reprice_status: string;
      priced: boolean;
      reason: string | null;
      probability: number | null;
    }>(`/api/v1/goals/${goalId}/evidence/manual`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entries }),
    }),
  addEvidence: async (goalId: string, evidenceText: string) =>
    watchThread(
      await request<WorkflowSnapshot>(`/api/v1/goals/${goalId}/evidence`, {
        method: "POST",
        headers: ASYNC_JSON_HEADERS,
        body: JSON.stringify({ kind: "add_evidence", evidence_text: evidenceText }),
      }),
    ),
  listUploads: (goalId: string, signal?: AbortSignal) =>
    request<UploadRecord[]>(`/api/v1/goals/${goalId}/uploads`, undefined, signal),
  uploadDataset: (goalId: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<UploadRecord>(`/api/v1/goals/${goalId}/uploads`, { method: "POST", body });
  },
  mapUpload: (
    goalId: string,
    uploadId: string,
    mapping: {
      metric: string;
      value_column: string;
      observed_at_column?: string;
      unit?: string;
      observation_kind?: string;
    },
  ) =>
    request<{ imported: number; reprice_status: string; priced: boolean; probability: number | null; reason: string | null }>(
      `/api/v1/goals/${goalId}/uploads/${uploadId}/map`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(mapping) },
    ),
  syncGithub: (goalId: string, login: string) =>
    request<WorkflowSnapshot>(`/api/v1/goals/${goalId}/github-sync`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: "add_evidence", github_login: login }),
    }),
  simulateWhatIf: (body: Record<string, unknown>) =>
    request<WhatIfResult>("/api/v1/what-if/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  fastReprice: (body: Record<string, unknown>) =>
    request<WhatIfResult>("/api/v1/what-if/fast-reprice", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }),
  targetSearch: (body: Record<string, unknown>) =>
    request<TargetSearchResult>("/api/v1/what-if/target-search", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }),
  actionFrontier: (body: Record<string, unknown>) =>
    request<ActionFrontierResult>("/api/v1/what-if/action-frontier", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }),
  possibleFutures: (body: Record<string, unknown>) =>
    request<ScenarioDistribution>("/api/v1/what-if/possible-futures", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }),
  comparePaths: (body: Record<string, unknown>) =>
    request<PathComparisonResult>("/api/v1/what-if/compare-paths", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }),
  parseIntervention: (body: { goal_id: string; text: string }) =>
    request<ParseInterventionResult>("/api/v1/what-if/parse-intervention", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }),
  parseDecision: (body: { goal_id: string; text: string }) =>
    request<ParseDecisionResult>("/api/v1/what-if/parse-decision", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }),
  courseGrade: (body: CourseGradeRequest) =>
    request<CourseGradeResult>("/api/v1/what-if/course-grade", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }),
  baselineState: (goalId: string, signal?: AbortSignal) =>
    request<WhatIfBaselineState>(`/api/v1/what-if/baseline-state/${goalId}`, undefined, signal),
  marketHistory: (goalId: string, signal?: AbortSignal) => request<MarketHistoryPoint[]>(`/api/v1/what-if/history/${goalId}`, undefined, signal),
  whatIfExplorations: (goalId: string, signal?: AbortSignal) =>
    request<WhatIfExploration[]>(`/api/v1/what-if/explorations/${goalId}`, undefined, signal),
  pluginsCatalog: (signal?: AbortSignal, search?: string, cursor?: string, browse = false) => {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (cursor) params.set("cursor", cursor);
    if (browse) params.set("browse", "true");
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return request<PluginCatalogResponse>(`/api/v1/plugins${suffix}`, undefined, signal);
  },
  plugins: async (signal?: AbortSignal, search?: string, cursor?: string) => {
    const body = await api.pluginsCatalog(signal, search, cursor);
    return body.items;
  },
  connectedPlugins: (signal?: AbortSignal) =>
    request<PluginView[]>("/api/v1/plugins/connected", undefined, signal),
  searchPlugins: (search: string, cursor?: string, signal?: AbortSignal) => {
    const params = new URLSearchParams({ search });
    if (cursor) params.set("cursor", cursor);
    return request<PluginCatalogResponse>(`/api/v1/plugins?${params.toString()}`, undefined, signal);
  },
  connectPlugin: (pluginId: string) =>
    request<PluginConnectResponse>(`/api/v1/plugins/${pluginId}/connect`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ gateway_provider: "composio" }),
    }),
  refreshPluginConnection: (pluginId: string) =>
    request<PluginConnectResponse>(`/api/v1/plugins/${pluginId}/connect/refresh`, { method: "POST" }),
  pluginCapabilities: (pluginId: string, signal?: AbortSignal) =>
    request<{ capability_id: string; label: string; operation: string; tool_name?: string | null; input_schema?: { properties?: Record<string, { type?: string }>; required?: string[]; parameters?: { properties?: Record<string, { type?: string }>; required?: string[] } } }[]>(
      `/api/v1/plugins/${pluginId}/capabilities`,
      undefined,
      signal,
    ),
  pluginAccess: (pluginId: string, signal?: AbortSignal) =>
    request<{ models: string[]; query_argument: string; query_label: string }>(
      `/api/v1/plugins/${pluginId}/access`,
      undefined,
      signal,
    ),
  pluginResources: (pluginId: string, signal?: AbortSignal) =>
    request<{ uri: string; name: string; description?: string; resource_type?: string; metadata?: { url?: string; provider_id?: string; connected_account_id?: string } }[]>(
      `/api/v1/plugins/${pluginId}/resources`,
      undefined,
      signal,
    ),
  previewPluginSource: (
    pluginId: string,
    body: { resource_id: string; resource_title?: string; resource_type?: string; arguments?: Record<string, string> },
  ) =>
    request<SourcePreview>(`/api/v1/plugins/${pluginId}/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  behaviorProfile: (goalId: string, signal?: AbortSignal) =>
    request<BehaviorProfile>(`/api/v1/goals/${goalId}/behavior-profile`, undefined, signal),
  disconnectPlugin: (pluginId: string) =>
    request<{ plugin_id: string; status: string }>(`/api/v1/plugins/${pluginId}/connect`, { method: "DELETE" }),
  evidenceSourcePlan: (goalId: string, signal?: AbortSignal) =>
    request<SourcePlannerProposal>(`/api/v1/goals/${goalId}/evidence/sources/plan`, undefined, signal),
  evidenceSourceRecipes: (goalId: string, signal?: AbortSignal) =>
    request<SourceRecipeRecord[]>(`/api/v1/goals/${goalId}/evidence/sources/recipes`, undefined, signal),
  sourceWatches: (goalId: string, signal?: AbortSignal) =>
    request<SourceWatchRecord[]>(`/api/v1/goals/${goalId}/evidence/sources/watches`, undefined, signal),
  saveSourceWatch: (goalId: string, body: { plugin_id: string; resource_id: string; scope: "resource" | "parent" }) =>
    request<SourceWatchRecord>(`/api/v1/goals/${goalId}/evidence/sources/watches`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }),
  updateSourceWatch: (goalId: string, watchId: string, status: "active" | "paused" | "revoked") =>
    request<SourceWatchRecord>(`/api/v1/goals/${goalId}/evidence/sources/watches/${watchId}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }),
    }),
  saveEvidenceSourceRecipe: (
    goalId: string,
    pluginId: string,
    body: { label: string; resource_ids: string[]; approved?: boolean; activity_types?: string[]; read_arguments?: Record<string, string> },
  ) =>
    request<SourceRecipeRecord>(`/api/v1/goals/${goalId}/evidence/sources/${pluginId}/recipe`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  syncEvidenceSources: (goalId: string) =>
    request<GoalSyncJob>(
      `/api/v1/goals/${goalId}/evidence/sources/sync`,
      { method: "POST" },
    ),
  latestEvidenceSourceSync: (goalId: string, signal?: AbortSignal) =>
    request<GoalSyncJob | null>(`/api/v1/goals/${goalId}/evidence/sources/sync`, undefined, signal),
  strategyLearning: (goalId: string, signal?: AbortSignal) =>
    request<StrategyLearningContext>(`/api/v1/goals/${goalId}/strategy-recommendations`, undefined, signal),
  generateStrategyRecommendation: (goalId: string) =>
    request<StrategyRecommendation>(`/api/v1/goals/${goalId}/strategy-recommendations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    }),
  strategyRecommendationFeedback: (goalId: string, recommendationId: string, decision: Exclude<StrategyDecision, "pending">) =>
    request<StrategyRecommendation>(`/api/v1/goals/${goalId}/strategy-recommendations/${recommendationId}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision }),
    }),
  strategyRecommendationOutcome: (goalId: string, recommendationId: string, attempted: boolean) =>
    request<Record<string, unknown>>(`/api/v1/goals/${goalId}/strategy-recommendations/${recommendationId}/outcomes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        idempotency_key: `self-report:${recommendationId}`,
        attempted,
        observed_at: new Date().toISOString(),
        observation_confidence: 1,
        outcome_kind: "intermediate",
      }),
    }),
};
