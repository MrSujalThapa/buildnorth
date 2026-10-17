begin;

create table goal_sync_recipes (
  goal_id uuid not null,
  plugin_id text not null,
  plugin_connection_id uuid not null references plugin_connections(id) on delete cascade,
  label text not null,
  steps_json jsonb not null,
  approved boolean not null default false,
  schema_version integer not null default 1,
  provenance_json jsonb not null default '{}'::jsonb,
  status text not null default 'approved',
  last_successful_sync_at timestamptz,
  user_approved_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (goal_id, plugin_id)
);

create index goal_sync_recipes_goal_id_idx on goal_sync_recipes (goal_id);

commit;
