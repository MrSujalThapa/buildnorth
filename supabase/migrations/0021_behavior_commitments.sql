begin;

create unique index if not exists goals_id_owner_uidx on goals(id, user_id);
create unique index if not exists plugin_connections_id_owner_uidx
  on plugin_connections(id, user_id);

alter table source_watches add constraint source_watches_owned_goal_fk
  foreign key (goal_id, owner_id) references goals(id, user_id);
alter table source_watches add constraint source_watches_owned_connection_fk
  foreign key (plugin_connection_id, owner_id)
  references plugin_connections(id, user_id);

create table if not exists behavior_commitments (
  id uuid primary key,
  owner_id uuid not null references app_users(id),
  goal_id uuid not null,
  domain text not null,
  action text not null,
  planned_quantity double precision not null check (planned_quantity > 0),
  unit text not null,
  window_start timestamptz not null,
  window_end timestamptz not null,
  created_at timestamptz not null default now(),
  check (window_end > window_start),
  foreign key (goal_id, owner_id) references goals(id, user_id),
  unique (id, owner_id)
);

create table if not exists behavior_commitment_observations (
  id uuid primary key,
  commitment_id uuid not null,
  owner_id uuid not null references app_users(id),
  version integer not null check (version > 0),
  status text not null check (status in
    ('completed', 'partial', 'missed', 'cancelled', 'unknown')),
  actual_quantity double precision check (actual_quantity >= 0),
  observed_at timestamptz not null,
  confidence double precision not null default 1 check (confidence between 0 and 1),
  source_quality text not null default 'user_confirmed',
  evidence_id uuid,
  created_at timestamptz not null default now(),
  foreign key (commitment_id, owner_id)
    references behavior_commitments(id, owner_id),
  unique (commitment_id, version)
);

create index if not exists behavior_commitments_owner_goal_idx
  on behavior_commitments (owner_id, goal_id, window_start desc);
create index if not exists behavior_commitment_observations_latest_idx
  on behavior_commitment_observations (commitment_id, version desc);
create unique index if not exists behavior_commitment_observations_evidence_idx
  on behavior_commitment_observations (commitment_id, evidence_id)
  where evidence_id is not null;

commit;
