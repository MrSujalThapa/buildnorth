begin;

-- Collapse rows that already share an owner fingerprint (they were meant to be
-- one observation). Then enforce uniqueness so concurrent inserts cannot fork.
with ranked as (
  select
    id,
    user_id,
    provenance_json ->> 'fingerprint' as fp,
    first_value(id) over (
      partition by user_id, provenance_json ->> 'fingerprint'
      order by created_at nulls last, id
    ) as keep_id
  from evidence_events
  where provenance_json ->> 'fingerprint' is not null
),
dups as (
  select id, keep_id from ranked where id <> keep_id
)
update evidence_events e
   set supersedes_id = d.keep_id
  from dups d
 where e.supersedes_id = d.id;

with ranked as (
  select
    id,
    first_value(id) over (
      partition by user_id, provenance_json ->> 'fingerprint'
      order by created_at nulls last, id
    ) as keep_id
  from evidence_events
  where provenance_json ->> 'fingerprint' is not null
),
dups as (
  select id, keep_id from ranked where id <> keep_id
)
insert into goal_evidence (goal_id, evidence_id, relevance_metadata_json)
select ge.goal_id, d.keep_id, '{}'::jsonb
  from goal_evidence ge
  join dups d on d.id = ge.evidence_id
on conflict do nothing;

with ranked as (
  select
    id,
    first_value(id) over (
      partition by user_id, provenance_json ->> 'fingerprint'
      order by created_at nulls last, id
    ) as keep_id
  from evidence_events
  where provenance_json ->> 'fingerprint' is not null
),
dups as (
  select id from ranked where id <> keep_id
)
delete from goal_evidence where evidence_id in (select id from dups);

with ranked as (
  select
    id,
    first_value(id) over (
      partition by user_id, provenance_json ->> 'fingerprint'
      order by created_at nulls last, id
    ) as keep_id
  from evidence_events
  where provenance_json ->> 'fingerprint' is not null
),
dups as (
  select id from ranked where id <> keep_id
)
delete from evidence_events where id in (select id from dups);

create unique index if not exists evidence_events_user_fingerprint_idx
  on evidence_events (user_id, (provenance_json ->> 'fingerprint'))
  where provenance_json ->> 'fingerprint' is not null;

commit;
