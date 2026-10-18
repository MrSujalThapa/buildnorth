begin;

alter table invitations
  add column if not exists max_redemptions integer not null default 1,
  add column if not exists redemption_count integer not null default 0;

update invitations
set redemption_count = 1
where redeemed_at is not null and redemption_count = 0;

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'invitations_max_redemptions_chk'
  ) then
    alter table invitations
      add constraint invitations_max_redemptions_chk
      check (max_redemptions >= 1 and max_redemptions <= 20);
  end if;
  if not exists (
    select 1 from pg_constraint where conname = 'invitations_redemption_count_chk'
  ) then
    alter table invitations
      add constraint invitations_redemption_count_chk
      check (redemption_count >= 0 and redemption_count <= max_redemptions);
  end if;
end $$;

create table if not exists invitation_redemptions (
  invitation_id uuid not null references invitations(id),
  user_id uuid not null references app_users(id),
  clerk_user_id text not null,
  redeemed_at timestamptz not null default now(),
  primary key (invitation_id, user_id)
);

create unique index if not exists invitation_redemptions_invite_clerk_idx
  on invitation_redemptions (invitation_id, clerk_user_id);

insert into invitation_redemptions (invitation_id, user_id, clerk_user_id, redeemed_at)
select i.id, i.redeemed_by, u.clerk_user_id, i.redeemed_at
from invitations i
join app_users u on u.id = i.redeemed_by
where i.redeemed_by is not null
  and i.redeemed_at is not null
on conflict (invitation_id, user_id) do nothing;

commit;
