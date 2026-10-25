begin;

alter table goals
  add column if not exists visibility text not null default 'private',
  add column if not exists published_at timestamptz,
  add column if not exists public_blueprint_json jsonb not null default '{}'::jsonb,
  add column if not exists forked_from_goal_id uuid,
  add column if not exists forked_from_user_id uuid,
  add column if not exists fork_idempotency_key text;

alter table goals drop constraint if exists goals_visibility_check;
alter table goals
  add constraint goals_visibility_check
  check (visibility in ('private', 'public'));

create index if not exists goals_public_published_idx
  on goals (published_at desc, id)
  where visibility = 'public' and status = 'active';

create index if not exists goals_owner_visibility_idx
  on goals (user_id, visibility, updated_at desc);

create unique index if not exists goals_fork_idempotency_uidx
  on goals (user_id, fork_idempotency_key)
  where fork_idempotency_key is not null;

create table if not exists market_stars (
  user_id uuid not null,
  goal_id uuid not null references goals(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (user_id, goal_id)
);

create index if not exists market_stars_goal_idx on market_stars (goal_id, created_at desc);

create table if not exists user_follows (
  follower_id uuid not null,
  followee_id uuid not null,
  created_at timestamptz not null default now(),
  primary key (follower_id, followee_id),
  constraint user_follows_no_self check (follower_id <> followee_id)
);

create index if not exists user_follows_followee_idx
  on user_follows (followee_id, created_at desc);

create table if not exists profile_activity_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  event_type text not null,
  goal_id uuid,
  occurred_on date not null,
  created_at timestamptz not null default now(),
  constraint profile_activity_type_check
    check (event_type in ('market_created', 'market_published', 'evidence_accepted'))
);

create unique index if not exists profile_activity_dedup_uidx
  on profile_activity_events (user_id, event_type, occurred_on, goal_id);

create index if not exists profile_activity_user_day_idx
  on profile_activity_events (user_id, occurred_on);

commit;
