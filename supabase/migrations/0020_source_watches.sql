begin;

create table if not exists source_watches (
  id uuid primary key,
  owner_id uuid not null references app_users(id),
  goal_id uuid not null references goals(id),
  plugin_connection_id uuid not null references plugin_connections(id),
  plugin_id text not null,
  resource_id text not null,
  scope text not null check (scope in ('resource', 'parent')),
  status text not null check (status in ('active', 'paused', 'revoked')),
  interval_minutes integer not null default 60 check (interval_minutes between 15 and 10080),
  next_check_at timestamptz not null default now(),
  last_checked_at timestamptz,
  last_success_at timestamptz,
  last_error text,
  cursor_value text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (owner_id, goal_id, plugin_connection_id, resource_id, scope)
);

create index if not exists source_watches_due_idx
  on source_watches (next_check_at) where status = 'active';
create index if not exists source_watches_owner_idx
  on source_watches (owner_id, goal_id);

commit;
