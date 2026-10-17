begin;

create table simulation_artifacts (
  id uuid primary key default gen_random_uuid(),
  goal_id uuid not null references goals(id),
  run_kind text not null check (run_kind in ('impact', 'target_search', 'possible_futures', 'path_comparison')),
  request_hash text not null unique,
  state_hash text not null,
  assumption_hash text not null,
  model_family text not null,
  model_version text not null,
  status text not null,
  receipt_json jsonb not null,
  created_at timestamptz not null default now()
);

create table market_forecast_history (
  id uuid primary key default gen_random_uuid(),
  goal_id uuid not null references goals(id),
  probability double precision not null check (probability between 0 and 1),
  forecast_status text not null,
  evidence_watermark text not null,
  model_family text not null,
  model_version text not null,
  assumption_hash text not null,
  material_hash text not null,
  simulation_artifact_id uuid not null references simulation_artifacts(id),
  created_at timestamptz not null default now(),
  unique (goal_id, material_hash)
);

create index simulation_artifacts_goal_created_idx
  on simulation_artifacts (goal_id, created_at desc);
create index market_forecast_history_goal_created_idx
  on market_forecast_history (goal_id, created_at desc);

create trigger simulation_artifacts_immutable before update or delete on simulation_artifacts
for each row execute function reject_immutable_mutation();
create trigger market_forecast_history_immutable before update or delete on market_forecast_history
for each row execute function reject_immutable_mutation();

comment on table simulation_artifacts is
  'Append-only What If run receipts; request_hash makes identical retries idempotent.';
comment on table market_forecast_history is
  'Immutable materially distinct probability snapshots used by the real market chart.';

commit;
