begin;

create table if not exists app_users (
  id uuid primary key,
  clerk_user_id text not null unique,
  email text,
  email_verified boolean not null default false,
  role text not null default 'user' check (role in ('user', 'admin')),
  created_at timestamptz not null default now()
);

create table if not exists invitations (
  id uuid primary key default gen_random_uuid(),
  token_hash text not null unique,
  email text,
  note text not null default '',
  hosted_quota_usd numeric not null default 2,
  hosted_quota_tokens integer not null default 100000,
  expires_at timestamptz not null,
  created_by uuid references app_users(id),
  created_at timestamptz not null default now(),
  revoked_at timestamptz,
  redeemed_at timestamptz,
  redeemed_by uuid references app_users(id)
);

create unique index if not exists invitations_unredeemed_token_idx
  on invitations (token_hash)
  where redeemed_at is null and revoked_at is null;

create table if not exists hosted_entitlements (
  user_id uuid primary key references app_users(id),
  enabled boolean not null default false,
  quota_usd numeric not null default 0,
  quota_tokens integer not null default 0,
  invitation_id uuid references invitations(id),
  granted_at timestamptz
);

create table if not exists hosted_budget_counters (
  scope text primary key,
  reserved_usd numeric not null default 0,
  spent_usd numeric not null default 0,
  reserved_tokens integer not null default 0,
  spent_tokens integer not null default 0
);

insert into hosted_budget_counters (scope)
values ('global')
on conflict (scope) do nothing;

create table if not exists inference_reservations (
  id uuid primary key,
  user_id uuid not null references app_users(id),
  clerk_user_id text not null,
  agent_name text not null,
  provider text not null,
  model text not null,
  reserved_usd numeric not null,
  reserved_tokens integer not null,
  status text not null check (status in ('reserved', 'settled', 'released')),
  created_at timestamptz not null default now(),
  settled_at timestamptz
);

create table if not exists inference_ledger (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  clerk_user_id text not null,
  reservation_id uuid references inference_reservations(id),
  agent_name text not null,
  provider text not null,
  model text not null,
  input_tokens integer not null default 0,
  output_tokens integer not null default 0,
  estimated_cost_usd numeric not null default 0,
  created_at timestamptz not null default now()
);

create table if not exists inference_rate_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid,
  ip_hash text,
  created_at timestamptz not null default now()
);

create table if not exists platform_controls (
  key text primary key,
  value_json jsonb not null
);

insert into platform_controls (key, value_json)
values ('hosted_inference_enabled', 'true'::jsonb)
on conflict (key) do nothing;

create index if not exists goals_user_id_idx on goals (user_id);
create index if not exists inference_reservations_user_status_idx
  on inference_reservations (user_id, status);
create index if not exists inference_rate_events_user_created_idx
  on inference_rate_events (user_id, created_at desc);
create index if not exists inference_rate_events_ip_created_idx
  on inference_rate_events (ip_hash, created_at desc);

commit;
