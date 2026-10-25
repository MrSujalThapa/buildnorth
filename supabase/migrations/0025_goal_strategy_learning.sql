begin;

-- 0023 is reserved by the unmerged marketplace branch. Strategy learning does
-- not depend on it or on the separate Pass 9A work.
create unique index if not exists evidence_events_id_owner_uidx
  on evidence_events(id, user_id);

create table strategy_recommendations (
  id uuid primary key,
  owner_id uuid not null references app_users(id),
  goal_id uuid not null,
  milestone_key text,
  strategy_key text not null check (length(strategy_key) between 2 and 100),
  action text not null check (length(action) between 3 and 1000),
  rationale text not null,
  next_step text not null,
  evidence_to_collect text not null,
  context_json jsonb not null,
  assumptions_json jsonb not null default '[]'::jsonb,
  provenance_json jsonb not null,
  expected_metric text not null,
  expected_unit text not null,
  expected_direction text not null check (expected_direction in ('increase','decrease','maintain')),
  expected_target double precision,
  evaluation_horizon timestamptz not null,
  proposed_at timestamptz not null,
  created_at timestamptz not null default now(),
  decision text not null default 'pending' check (decision in ('pending','accepted','declined','ignored')),
  decided_at timestamptz,
  fingerprint text not null,
  population_learning_consented boolean not null default false,
  unique (id, owner_id),
  unique (owner_id, goal_id, fingerprint),
  foreign key (goal_id, owner_id) references goals(id, user_id),
  check (evaluation_horizon > proposed_at),
  check ((decision = 'pending') = (decided_at is null))
);

create table strategy_outcome_observations (
  id uuid primary key,
  recommendation_id uuid not null,
  owner_id uuid not null,
  idempotency_key text not null,
  attempted boolean,
  outcome_kind text not null default 'intermediate' check (outcome_kind in ('intermediate','final')),
  observed_value double precision,
  status text not null check (status in
    ('pending','successful','unsuccessful','inconclusive','insufficient_evidence')),
  observation_confidence double precision not null check (observation_confidence between 0 and 1),
  provenance_json jsonb not null,
  observed_at timestamptz not null,
  created_at timestamptz not null default now(),
  foreign key (recommendation_id, owner_id)
    references strategy_recommendations(id, owner_id),
  unique (id, owner_id),
  unique (recommendation_id, idempotency_key)
);

create table strategy_outcome_evidence (
  observation_id uuid not null,
  owner_id uuid not null,
  goal_id uuid not null,
  evidence_id uuid not null,
  primary key (observation_id, evidence_id),
  foreign key (observation_id, owner_id)
    references strategy_outcome_observations(id, owner_id),
  foreign key (evidence_id, owner_id) references evidence_events(id, user_id),
  foreign key (goal_id, evidence_id) references goal_evidence(goal_id, evidence_id)
);

create trigger strategy_outcome_observations_immutable
  before update or delete on strategy_outcome_observations
  for each row execute function reject_immutable_mutation();

create index strategy_recommendations_context_idx
  on strategy_recommendations(owner_id, goal_id, proposed_at desc);
create index strategy_outcomes_latest_idx
  on strategy_outcome_observations(recommendation_id, observed_at desc, created_at desc);

commit;
