begin;

create table plugin_connections (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  plugin_id text not null,
  connection_type text not null check (connection_type in ('managed_gateway', 'custom_mcp')),
  gateway_provider text,
  transport text not null default 'stdio',
  auth_ref text,
  status text not null default 'pending',
  account_metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  last_verified_at timestamptz,
  last_sync_at timestamptz,
  unique (user_id, plugin_id)
);

create table mcp_connections (
  id uuid primary key default gen_random_uuid(),
  plugin_connection_id uuid not null references plugin_connections(id) on delete cascade,
  server_label text not null,
  endpoint text,
  transport text not null,
  auth_ref text,
  status text not null default 'pending',
  created_at timestamptz not null default now(),
  last_verified_at timestamptz
);

create table read_capabilities (
  id uuid primary key default gen_random_uuid(),
  plugin_connection_id uuid not null references plugin_connections(id) on delete cascade,
  capability_id text not null,
  label text not null,
  operation text not null,
  tool_name text,
  resource_uri text,
  input_schema_json jsonb not null default '{}'::jsonb,
  approved boolean not null default false,
  created_at timestamptz not null default now(),
  unique (plugin_connection_id, capability_id)
);

create table sync_recipes (
  id uuid primary key default gen_random_uuid(),
  plugin_connection_id uuid not null references plugin_connections(id) on delete cascade,
  recipe_version integer not null default 1,
  steps_json jsonb not null,
  validated_at timestamptz not null default now(),
  unique (plugin_connection_id, recipe_version)
);

create table sync_cursors (
  id uuid primary key default gen_random_uuid(),
  plugin_connection_id uuid not null references plugin_connections(id) on delete cascade,
  capability_id text not null,
  cursor_value text,
  updated_at timestamptz not null default now(),
  unique (plugin_connection_id, capability_id)
);

create table sync_runs (
  id uuid primary key default gen_random_uuid(),
  plugin_connection_id uuid not null references plugin_connections(id) on delete cascade,
  status text not null,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  records_read integer not null default 0,
  records_new integer not null default 0,
  error text
);

alter table raw_source_events
  add column if not exists plugin_connection_id uuid references plugin_connections(id),
  add column if not exists sync_run_id uuid references sync_runs(id),
  add column if not exists payload_hash text,
  add column if not exists tool_identity text,
  add column if not exists retrieved_at timestamptz;

commit;
