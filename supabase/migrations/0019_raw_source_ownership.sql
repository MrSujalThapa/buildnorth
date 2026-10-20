begin;

-- Provider event identifiers are shared across accounts. Keep deduplication within
-- the owner's evidence history instead of suppressing another user's records.
alter table raw_source_events
  drop constraint if exists raw_source_events_source_type_external_event_id_key;
alter table raw_source_events
  drop constraint if exists raw_source_events_source_type_content_fingerprint_key;

create unique index if not exists raw_source_events_owner_external_idx
  on raw_source_events (user_id, source_type, external_event_id)
  where user_id is not null and external_event_id is not null;
create unique index if not exists raw_source_events_owner_fingerprint_idx
  on raw_source_events (user_id, source_type, content_fingerprint)
  where user_id is not null;

alter table raw_source_events add column if not exists goal_sync_job_id uuid
  references goal_sync_jobs(id);
create index if not exists raw_source_events_goal_sync_job_idx
  on raw_source_events (goal_sync_job_id)
  where goal_sync_job_id is not null;

commit;
