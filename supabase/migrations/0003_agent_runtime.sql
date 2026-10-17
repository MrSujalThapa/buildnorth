begin;

create table if not exists workflow_threads (
  id uuid primary key,
  user_id uuid not null,
  kind text not null,
  status text not null,
  current_step text not null default 'parse_request',
  interrupt_payload jsonb,
  goal_id uuid references goals(id),
  result_json jsonb not null default '{}'::jsonb,
  idempotency_key text unique,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table agent_runs add column if not exists thread_id uuid;
alter table agent_runs add column if not exists prompt_version text;
alter table agent_runs add column if not exists prompt_checksum text;
alter table agent_runs add column if not exists tool_trace_json jsonb not null default '[]'::jsonb;
alter table agent_runs add column if not exists validation_errors_json jsonb not null default '[]'::jsonb;
alter table agent_runs add column if not exists input_artifact_ids_json jsonb not null default '[]'::jsonb;
alter table agent_runs add column if not exists interrupt_json jsonb;
alter table agent_runs add column if not exists status text not null default 'completed';

create table if not exists openai_usage_daily (
  usage_date date not null,
  pool text not null,
  model text not null,
  input_tokens bigint not null default 0,
  output_tokens bigint not null default 0,
  estimated_cost_usd numeric not null default 0,
  primary key (usage_date, pool, model)
);

create table if not exists github_sync_cursors (
  user_id uuid not null,
  login text not null,
  cursor text,
  last_synced_at timestamptz,
  primary key (user_id, login)
);

create table if not exists forecast_reviews (
  id uuid primary key default gen_random_uuid(),
  goal_id uuid not null references goals(id),
  thread_id uuid not null,
  priced boolean not null,
  forecast_status text not null,
  critic_decision text not null,
  limitations_json jsonb not null default '[]'::jsonb,
  receipt_json jsonb not null,
  agent_run_ids_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists csv_import_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  goal_id uuid references goals(id),
  filename text not null,
  mapping_json jsonb not null,
  status text not null,
  error text,
  created_at timestamptz not null default now()
);

create index if not exists workflow_threads_user_idx on workflow_threads (user_id, updated_at desc);
create index if not exists agent_runs_thread_idx on agent_runs (thread_id, created_at);
create index if not exists forecast_reviews_goal_idx on forecast_reviews (goal_id, created_at desc);

commit;
