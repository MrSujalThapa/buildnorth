begin;
create table if not exists goal_research_artifacts (
  id uuid primary key,
  user_id uuid not null references app_users(id),
  goal_id uuid not null references goals(id),
  artifact_json jsonb not null,
  created_at timestamptz not null default now()
);
create index if not exists goal_research_owner_goal_idx
  on goal_research_artifacts(user_id, goal_id, created_at);
alter table goal_research_artifacts enable row level security;
revoke all on goal_research_artifacts from public;
drop trigger if exists goal_research_immutable on goal_research_artifacts;
create trigger goal_research_immutable before update or delete on goal_research_artifacts
  for each row execute function reject_immutable_mutation();
commit;
