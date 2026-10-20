begin;

alter table app_users
  add column if not exists display_name text,
  add column if not exists username text,
  add column if not exists bio text,
  add column if not exists avatar_value text;

create unique index if not exists app_users_username_lower_idx
  on app_users (lower(username))
  where username is not null;

alter table app_users
  add constraint app_users_username_format
  check (
    username is null
    or username ~ '^[a-z0-9_]{3,24}$'
  );

alter table app_users
  add constraint app_users_display_name_len
  check (display_name is null or char_length(display_name) between 1 and 80);

alter table app_users
  add constraint app_users_bio_len
  check (bio is null or char_length(bio) <= 280);

alter table app_users
  add constraint app_users_avatar_len
  check (avatar_value is null or char_length(avatar_value) <= 32);

create table if not exists collections (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  name text not null check (char_length(name) between 1 and 80),
  description text not null default '',
  icon text,
  color text,
  position integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists collections_user_position_idx
  on collections (user_id, position, created_at);

create table if not exists collection_goals (
  collection_id uuid not null references collections(id) on delete cascade,
  goal_id uuid not null references goals(id),
  position integer not null default 0,
  added_at timestamptz not null default now(),
  primary key (collection_id, goal_id)
);

create index if not exists collection_goals_goal_idx on collection_goals (goal_id);

commit;
