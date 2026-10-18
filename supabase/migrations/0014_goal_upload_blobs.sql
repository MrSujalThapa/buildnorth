begin;
alter table goal_uploads add column if not exists content bytea;
alter table goal_uploads add column if not exists deleted_at timestamptz;

drop index if exists goal_uploads_owner_goal_hash_idx;
create unique index if not exists goal_uploads_live_hash_idx
  on goal_uploads(user_id, goal_id, sha256)
  where deleted_at is null;

create index if not exists goal_uploads_owner_live_idx
  on goal_uploads(user_id)
  where deleted_at is null;
commit;
