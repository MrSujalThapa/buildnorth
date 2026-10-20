begin;

create table if not exists profile_photos (
  user_id uuid primary key references app_users(id) on delete cascade,
  content_type text not null check (content_type = 'image/webp'),
  content bytea not null,
  updated_at timestamptz not null default now()
);

alter table app_users
  add column if not exists profile_dimensions_json jsonb not null default '[]'::jsonb;

create index if not exists profile_photos_updated_at_idx on profile_photos(updated_at);

commit;
