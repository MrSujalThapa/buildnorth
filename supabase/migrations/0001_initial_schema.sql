begin;

create extension if not exists pgcrypto;

create type goal_type as enum ('deadline_event', 'threshold', 'continuous_target', 'habit', 'multi_outcome');
create type forecast_status as enum ('CALIBRATED', 'ANCHORED', 'EXPLORATORY');

create table goals (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  title text not null check (length(title) between 3 and 200),
  description text not null default '',
  goal_type goal_type not null,
  success_definition_json jsonb not null check (success_definition_json <> '{}'::jsonb),
  deadline timestamptz not null,
  status text not null default 'active',
  target_probability double precision check (target_probability between 0 and 1),
  forecast_status forecast_status not null default 'EXPLORATORY',
  resource_constraints_json jsonb not null default '{}'::jsonb,
  state_dimensions_json jsonb not null default '[]'::jsonb,
  model_requirements_json jsonb not null default '{}'::jsonb,
  version integer not null default 1 check (version > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table source_connections (
  id uuid primary key default gen_random_uuid(), user_id uuid not null, provider text not null,
  scope_json jsonb not null default '{}'::jsonb, status text not null,
  external_account_ref text, cursor text, last_synced_at timestamptz, created_at timestamptz not null default now()
);

create table raw_source_events (
  id uuid primary key default gen_random_uuid(), connection_id uuid references source_connections(id),
  source_type text not null, external_event_id text, content_fingerprint text not null,
  observed_at timestamptz not null, ingested_at timestamptz not null default now(),
  raw_payload_ref text not null, status text not null default 'received',
  unique (source_type, external_event_id), unique (source_type, content_fingerprint)
);

create table agent_runs (
  id uuid primary key default gen_random_uuid(), agent_type text not null, agent_version text not null,
  model_provider text, model_name text, input_refs_json jsonb not null default '[]'::jsonb,
  output_json jsonb, tool_trace_ref text, validation_status text not null,
  retry_count integer not null default 0 check (retry_count >= 0), duration_ms integer,
  token_usage_json jsonb, estimated_cost numeric, created_at timestamptz not null default now()
);

create table evidence_events (
  id uuid primary key default gen_random_uuid(), user_id uuid not null,
  raw_source_event_id uuid references raw_source_events(id), event_type text not null,
  domain text not null, metric text not null, numeric_value double precision,
  categorical_value text, unit text, observed_at timestamptz not null,
  source_quality text not null, provenance_json jsonb not null,
  supersedes_id uuid references evidence_events(id), status text not null default 'active',
  agent_run_id uuid references agent_runs(id), created_at timestamptz not null default now(),
  check (numeric_value is not null or categorical_value is not null)
);

create table goal_evidence (
  goal_id uuid not null references goals(id), evidence_id uuid not null references evidence_events(id),
  relevance_metadata_json jsonb not null default '{}'::jsonb, primary key (goal_id, evidence_id)
);

create table state_snapshots (
  id uuid primary key default gen_random_uuid(), goal_id uuid not null references goals(id),
  as_of timestamptz not null, version integer not null check (version > 0),
  state_vector_json jsonb not null, uncertainty_json jsonb not null,
  estimator_version text not null, evidence_watermark timestamptz not null,
  created_at timestamptz not null default now(), unique (goal_id, version)
);

create table reference_datasets (
  id uuid primary key default gen_random_uuid(), name text not null, domain text not null,
  version text not null, source text not null, license text not null,
  population_definition text not null, outcome_definition text not null,
  feature_schema_json jsonb not null, checksum text not null, notes text not null default '',
  unique (name, version)
);

create table model_versions (
  id uuid primary key default gen_random_uuid(), family text not null, version text not null,
  artifact_uri text not null, artifact_checksum text not null,
  training_dataset_ids uuid[] not null default '{}', feature_schema_version text not null,
  calibration_version text, metrics_json jsonb, created_at timestamptz not null default now(),
  unique (family, version)
);

create table forecasts (
  id uuid primary key default gen_random_uuid(), goal_id uuid not null references goals(id),
  state_snapshot_id uuid not null references state_snapshots(id),
  model_version_id uuid not null references model_versions(id),
  raw_probability double precision not null check (raw_probability between 0 and 1),
  calibrated_probability double precision check (calibrated_probability between 0 and 1),
  forecast_status forecast_status not null, critic_decision text not null,
  limitations_json jsonb not null default '[]'::jsonb, created_at timestamptz not null default now(),
  unique (goal_id, state_snapshot_id, model_version_id)
);

create table forecast_receipts (
  id uuid primary key default gen_random_uuid(), forecast_id uuid not null unique references forecasts(id),
  receipt_version integer not null, inputs_json jsonb not null, feature_transforms_json jsonb not null,
  model_details_json jsonb not null, assumptions_json jsonb not null,
  simulation_config_json jsonb, contributions_json jsonb, calibration_json jsonb,
  provenance_json jsonb not null, created_at timestamptz not null default now()
);

create table actions (
  id uuid primary key default gen_random_uuid(), goal_id uuid not null references goals(id),
  title text not null, action_type text not null, parameterization_json jsonb not null,
  cost_json jsonb not null, prerequisites_json jsonb not null default '[]'::jsonb,
  exclusivity_group text, created_at timestamptz not null default now()
);

create table scenarios (
  id uuid primary key default gen_random_uuid(), goal_id uuid not null references goals(id),
  name text not null, scenario_type text not null, intervention_json jsonb not null,
  assumptions_json jsonb not null, resource_constraints_json jsonb not null,
  created_at timestamptz not null default now()
);

create table simulation_runs (
  id uuid primary key default gen_random_uuid(), scenario_id uuid not null references scenarios(id),
  state_snapshot_id uuid not null references state_snapshots(id),
  model_version_id uuid not null references model_versions(id), seed bigint not null,
  n_paths integer not null check (n_paths > 0), engine_version text not null,
  config_hash text not null, status text not null, aggregate_result_json jsonb,
  duration_ms integer, created_at timestamptz not null default now(),
  unique (scenario_id, state_snapshot_id, model_version_id, config_hash)
);

create table scenario_outcomes (
  id uuid primary key default gen_random_uuid(), simulation_run_id uuid not null references simulation_runs(id),
  label text not null, probability double precision not null check (probability between 0 and 1),
  definition_json jsonb not null, representative_path_json jsonb,
  unique (simulation_run_id, label)
);

create table evaluation_runs (
  id uuid primary key default gen_random_uuid(), benchmark_name text not null,
  benchmark_version text not null, system_variant text not null,
  model_versions_json jsonb not null, split_hash text not null, random_seed bigint not null,
  metrics_json jsonb, artifact_uri text not null, created_at timestamptz not null default now()
);

create index raw_source_events_observed_at_idx on raw_source_events (observed_at);
create index evidence_events_user_observed_idx on evidence_events (user_id, observed_at);
create index state_snapshots_goal_as_of_idx on state_snapshots (goal_id, as_of desc);
create index forecasts_goal_created_idx on forecasts (goal_id, created_at desc);
create index agent_runs_created_idx on agent_runs (created_at desc);

comment on table forecasts is 'Append-only immutable forecast artifacts; UPDATE/DELETE must be denied at the application role.';
comment on table state_snapshots is 'Append-only immutable state snapshots.';

commit;
