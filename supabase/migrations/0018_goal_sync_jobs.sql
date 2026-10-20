begin;

create table if not exists goal_sync_jobs (
  id uuid primary key,
  owner_id uuid not null references app_users(id),
  goal_id uuid not null references goals(id),
  status text not null default 'queued' check (status in (
    'queued', 'fetching_sources', 'processing_evidence',
    'updating_forecast', 'completed', 'failed', 'timed_out'
  )),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  receipt jsonb not null default '{}'::jsonb,
  error text
);

create unique index if not exists goal_sync_jobs_one_active_idx
  on goal_sync_jobs (owner_id, goal_id)
  where status in ('queued', 'fetching_sources', 'processing_evidence', 'updating_forecast');

create index if not exists goal_sync_jobs_owner_recent_idx
  on goal_sync_jobs (owner_id, goal_id, created_at desc);

commit;
