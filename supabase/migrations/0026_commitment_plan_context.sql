begin;

-- A plan adopted from What If keeps the scenario it was priced under. Planned
-- actions are never evidence; outcomes still arrive as immutable observations.
alter table behavior_commitments
  add column if not exists plan_context jsonb;

commit;
