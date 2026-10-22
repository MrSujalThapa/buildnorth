begin;

-- Radar trait selection and user-defined traits. Additive; legacy rows keep '{}'
-- and fall back to the default trait selection.
alter table app_users
  add column if not exists profile_parameters_json jsonb not null default '{}'::jsonb;

-- Ownership registry for seeded workspace fixtures so they stay identifiable and
-- removable without touching records the user created.
create table if not exists workspace_seed_records (
  owner_id uuid not null references app_users(id) on delete cascade,
  seed_version text not null,
  entity_type text not null,
  entity_id uuid not null,
  created_at timestamptz not null default now(),
  primary key (owner_id, entity_type, entity_id)
);

create index if not exists workspace_seed_records_owner_idx
  on workspace_seed_records(owner_id, seed_version);

commit;
