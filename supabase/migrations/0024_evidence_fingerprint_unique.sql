begin;

-- Relink dependents onto the surviving observation, then keep duplicate rows as
-- superseded history. Do not delete evidence events: receipts and provenance may
-- still name them. Unique among live (not superseded) fingerprints only.

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
    and supersedes_id is null
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
    and supersedes_id is null
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
    and supersedes_id is null
),
dups as (
  select id, keep_id from ranked where id <> keep_id
)
update evidence_events e
   set supersedes_id = d.keep_id
  from dups d
 where e.id = d.id;

update behavior_commitment_observations o
   set evidence_id = e.supersedes_id
  from evidence_events e
 where o.evidence_id = e.id
   and e.supersedes_id is not null
   and not exists (
     select 1
       from behavior_commitment_observations existing
      where existing.commitment_id = o.commitment_id
        and existing.evidence_id = e.supersedes_id
   );

create unique index if not exists evidence_events_user_fingerprint_live_idx
  on evidence_events (user_id, (provenance_json ->> 'fingerprint'))
  where provenance_json ->> 'fingerprint' is not null
    and supersedes_id is null;

commit;
