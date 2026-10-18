import { currentAccessToken, type AccountView } from "../auth/session";

export type ForecastStatus = "CALIBRATED" | "ANCHORED" | "EXPLORATORY";

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

export interface Goal {
  goal_id: string;
  title: string;
  goal_type: "deadline_event" | "threshold" | "continuous_target" | "habit" | "multi_outcome";
  deadline: string;
  forecast_status: ForecastStatus;
  state_dimensions: string[];
  success_definition?: Record<string, unknown>;
  resource_constraints?: { hours_per_week?: number; budget_amount?: number; budget_currency?: string };
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
  paths: { label: string; action_ids: string[]; resulting_probability: number; resource_cost: { hours_per_week: number; money: number; energy: number }; fragility_pp: number | null; valid_because: string }[];
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
  paths: { id: string; label: string; primary_goal_probability: number; expected_outcome: number; median: number; p10: number; p90: number; downside_probability: number; fragility_pp: number | null; resource_cost: { hours_per_week: number; money: number; energy: number }; execution_probability: number; model_status: string }[];
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
  steps: { capability_id: string; tool_name?: string | null; arguments: Record<string, unknown> }[];
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
  periods?: number | null;
  direction: "at_least" | "at_most";
  current_probability?: number | null;
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
  definition: { id: string; name: string; description: string; category: string; provider_type: string; logo_url?: string | null; capabilities: { id: string; label: string; operation: string }[]; used_for: string[] };
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
  source_type: "manual" | "github" | "csv";
  summary: string;
}

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

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL;
const baseUrl = configuredBaseUrl || `${window.location.protocol}//${window.location.hostname}:8000`;

async function request<T>(path: string, init?: RequestInit, signal?: AbortSignal): Promise<T> {
  const token = await currentAccessToken();
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    signal,
    headers: {
      Accept: "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
  });
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
  return (await response.json()) as T;
}

export const api = {
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
  health: (signal?: AbortSignal) => request<Health>("/health", undefined, signal),
  goals: (signal?: AbortSignal) => request<Goal[]>("/api/v1/goals", undefined, signal),
  goal: (goalId: string, signal?: AbortSignal) => request<Goal>(`/api/v1/goals/${goalId}`, undefined, signal),
  evidence: (goalId: string, signal?: AbortSignal) =>
    request<EvidenceEvent[]>(`/api/v1/goals/${goalId}/evidence`, undefined, signal),
  startThread: (body: { kind: string; intent?: string; goal_id?: string; evidence_text?: string; github_login?: string }) =>
    request<WorkflowSnapshot>("/api/v1/agent/threads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  resumeThread: (threadId: string, body: { answers?: Record<string, string>; confirmed?: boolean; cancelled?: boolean }) =>
    request<WorkflowSnapshot>(`/api/v1/agent/threads/${threadId}/resume`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
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
  addEvidence: (goalId: string, evidenceText: string) =>
    request<WorkflowSnapshot>(`/api/v1/goals/${goalId}/evidence`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: "add_evidence", evidence_text: evidenceText }),
    }),
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
  baselineState: (goalId: string, signal?: AbortSignal) =>
    request<WhatIfBaselineState>(`/api/v1/what-if/baseline-state/${goalId}`, undefined, signal),
  marketHistory: (goalId: string, signal?: AbortSignal) => request<MarketHistoryPoint[]>(`/api/v1/what-if/history/${goalId}`, undefined, signal),
  whatIfExplorations: (goalId: string, signal?: AbortSignal) =>
    request<WhatIfExploration[]>(`/api/v1/what-if/explorations/${goalId}`, undefined, signal),
  plugins: async (signal?: AbortSignal, search?: string, cursor?: string) => {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (cursor) params.set("cursor", cursor);
    const suffix = params.toString() ? `?${params.toString()}` : "";
    const body = await request<PluginCatalogResponse>(`/api/v1/plugins${suffix}`, undefined, signal);
    return body.items;
  },
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
    request<{ capability_id: string; label: string; operation: string; tool_name?: string | null }[]>(
      `/api/v1/plugins/${pluginId}/capabilities`,
      undefined,
      signal,
    ),
  pluginResources: (pluginId: string, signal?: AbortSignal) =>
    request<{ uri: string; name: string; description?: string; resource_type?: string }[]>(
      `/api/v1/plugins/${pluginId}/resources`,
      undefined,
      signal,
    ),
  behaviorProfile: (goalId: string, signal?: AbortSignal) =>
    request<BehaviorProfile>(`/api/v1/goals/${goalId}/behavior-profile`, undefined, signal),
  disconnectPlugin: (pluginId: string) =>
    request<{ plugin_id: string; status: string }>(`/api/v1/plugins/${pluginId}/connect`, { method: "DELETE" }),
  evidenceSourcePlan: (goalId: string, signal?: AbortSignal) =>
    request<SourcePlannerProposal>(`/api/v1/goals/${goalId}/evidence/sources/plan`, undefined, signal),
  evidenceSourceRecipes: (goalId: string, signal?: AbortSignal) =>
    request<SourceRecipeRecord[]>(`/api/v1/goals/${goalId}/evidence/sources/recipes`, undefined, signal),
  saveEvidenceSourceRecipe: (
    goalId: string,
    pluginId: string,
    body: { label: string; resource_ids: string[]; approved?: boolean; activity_types?: string[] },
  ) =>
    request<SourceRecipeRecord>(`/api/v1/goals/${goalId}/evidence/sources/${pluginId}/recipe`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  syncEvidenceSources: (goalId: string) =>
    request<WorkflowSnapshot | { status: string; message?: string }>(
      `/api/v1/goals/${goalId}/evidence/sources/sync`,
      { method: "POST" },
    ),
};
