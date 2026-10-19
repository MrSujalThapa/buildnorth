begin;

-- Remote MCP authorization server state. Tokens and codes are stored only as SHA-256
-- digests; raw values are returned to the OAuth client once and never persisted.
create table if not exists remote_mcp_oauth_clients (
  client_id text primary key,
  client_name text,
  client_uri text,
  redirect_uris jsonb not null,
  token_endpoint_auth_method text not null default 'none',
  client_secret_ciphertext text,
  metadata_json jsonb not null default '{}'::jsonb,
  registration_ip_hash text,
  created_at timestamptz not null default now()
);

create table if not exists remote_mcp_authorization_requests (
  id text primary key,
  client_id text not null references remote_mcp_oauth_clients(client_id),
  redirect_uri text not null,
  redirect_uri_provided_explicitly boolean not null,
  scopes jsonb not null,
  code_challenge text not null,
  state text,
  resource text,
  expires_at timestamptz not null,
  decided_at timestamptz,
  decided_by uuid references app_users(id),
  decision text check (decision in ('approved', 'denied')),
  created_at timestamptz not null default now()
);

create table if not exists remote_mcp_connections (
  id uuid primary key,
  user_id uuid not null references app_users(id),
  client_id text not null references remote_mcp_oauth_clients(client_id),
  client_name text,
  scopes jsonb not null,
  resource text not null,
  created_at timestamptz not null default now(),
  last_used_at timestamptz,
  revoked_at timestamptz
);
create index if not exists remote_mcp_connections_user_idx on remote_mcp_connections(user_id, created_at desc);

create table if not exists remote_mcp_authorization_codes (
  code_hash text primary key,
  connection_id uuid references remote_mcp_connections(id),
  client_id text not null,
  user_id uuid not null references app_users(id),
  redirect_uri text not null,
  redirect_uri_provided_explicitly boolean not null,
  scopes jsonb not null,
  code_challenge text not null,
  resource text not null,
  expires_at timestamptz not null,
  consumed_at timestamptz
);

create table if not exists remote_mcp_tokens (
  token_hash text primary key,
  kind text not null check (kind in ('access', 'refresh')),
  connection_id uuid not null references remote_mcp_connections(id),
  client_id text not null,
  user_id uuid not null references app_users(id),
  scopes jsonb not null,
  resource text not null,
  expires_at timestamptz not null,
  revoked_at timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists remote_mcp_tokens_connection_idx on remote_mcp_tokens(connection_id);

-- Idempotency ledger for external evidence submissions. The unique key is claimed
-- before evidence is committed so concurrent retries cannot double count.
create table if not exists remote_mcp_evidence_submissions (
  user_id uuid not null references app_users(id),
  idempotency_key text not null,
  goal_id uuid not null,
  connection_id uuid,
  payload_hash text not null,
  status text not null check (status in ('pending', 'committed', 'failed')),
  result_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, idempotency_key)
);

-- Audit metadata only: tool name, outcome and identifiers. No evidence text, tokens or
-- arguments are written here.
create table if not exists remote_mcp_audit_log (
  id uuid primary key default gen_random_uuid(),
  user_id uuid,
  connection_id uuid,
  client_id text,
  event text not null,
  tool_name text,
  outcome text not null,
  detail_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists remote_mcp_audit_log_user_idx on remote_mcp_audit_log(user_id, created_at desc);

alter table remote_mcp_oauth_clients enable row level security;
alter table remote_mcp_authorization_requests enable row level security;
alter table remote_mcp_connections enable row level security;
alter table remote_mcp_authorization_codes enable row level security;
alter table remote_mcp_tokens enable row level security;
alter table remote_mcp_evidence_submissions enable row level security;
alter table remote_mcp_audit_log enable row level security;
revoke all on remote_mcp_oauth_clients from public;
revoke all on remote_mcp_authorization_requests from public;
revoke all on remote_mcp_connections from public;
revoke all on remote_mcp_authorization_codes from public;
revoke all on remote_mcp_tokens from public;
revoke all on remote_mcp_evidence_submissions from public;
revoke all on remote_mcp_audit_log from public;

commit;
