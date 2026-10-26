begin;

-- Archived forks must not block a later fork of the same public market.
-- One active fork per owner and source; retries of the same key stay idempotent.
drop index if exists goals_fork_idempotency_uidx;

create unique index goals_fork_idempotency_uidx
  on goals (user_id, fork_idempotency_key)
  where fork_idempotency_key is not null and status = 'active';

create unique index if not exists goals_active_fork_source_uidx
  on goals (user_id, forked_from_goal_id)
  where forked_from_goal_id is not null and status = 'active';

commit;
