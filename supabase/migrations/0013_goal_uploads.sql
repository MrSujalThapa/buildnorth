begin;
create table if not exists goal_uploads (
  id uuid primary key,
  user_id uuid not null references app_users(id),
  goal_id uuid not null references goals(id),
  filename text not null,
  content_type text not null,
  byte_size integer not null,
  sha256 text not null,
  storage_path text not null,
  status text not null,
  preview_json jsonb not null default '{}'::jsonb,
  mapping_json jsonb,
  lineage_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create unique index if not exists goal_uploads_owner_goal_hash_idx
  on goal_uploads(user_id, goal_id, sha256);
create index if not exists goal_uploads_owner_goal_idx
  on goal_uploads(user_id, goal_id, created_at);
alter table goal_uploads enable row level security;
revoke all on goal_uploads from public;
commit;
