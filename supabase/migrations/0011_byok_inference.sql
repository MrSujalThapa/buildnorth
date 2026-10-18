begin;

create table if not exists provider_credentials (
  user_id uuid not null references app_users(id),
  provider text not null check (provider in ('openai', 'anthropic')),
  ciphertext text not null,
  suffix text not null check (length(suffix) <= 4),
  version uuid not null,
  validated_at timestamptz not null,
  status text not null default 'validated' check (status in ('validated', 'invalid')),
  primary key (user_id, provider)
);
alter table provider_credentials add column if not exists status text not null default 'validated'
  check (status in ('validated', 'invalid'));
create table if not exists inference_preferences (
  user_id uuid primary key references app_users(id),
  mode text not null default 'hosted' check (mode in ('hosted', 'byok')),
  provider text not null default 'openai' check (provider in ('openai', 'anthropic')),
  model text
);
-- Application server is the only reader/writer. No public/client DB access to secrets.
alter table provider_credentials enable row level security;
alter table inference_preferences enable row level security;
revoke all on provider_credentials, inference_preferences from public;

alter table inference_ledger add column if not exists billing_mode text not null default 'hosted'
  check (billing_mode in ('hosted', 'byok'));
alter table inference_ledger add column if not exists credential_version uuid;
alter table inference_ledger add column if not exists outcome text not null default 'success';
alter table inference_ledger add column if not exists latency_ms integer not null default 0;
alter table inference_ledger add column if not exists execution_id uuid;
alter table inference_ledger add column if not exists usage_reported boolean not null default true;
create unique index if not exists inference_ledger_execution_idx
  on inference_ledger(execution_id) where execution_id is not null;
create index if not exists inference_ledger_daily_idx
  on inference_ledger(created_at, billing_mode);

commit;
