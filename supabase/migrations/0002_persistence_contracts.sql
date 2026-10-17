begin;

alter table raw_source_events add column user_id uuid;
alter table raw_source_events add column raw_payload_json jsonb not null default '{}'::jsonb;

create or replace function reject_immutable_mutation() returns trigger
language plpgsql as $$
begin
  raise exception '% is append-only', tg_table_name;
end;
$$;

create trigger state_snapshots_immutable before update or delete on state_snapshots
for each row execute function reject_immutable_mutation();
create trigger forecasts_immutable before update or delete on forecasts
for each row execute function reject_immutable_mutation();
create trigger forecast_receipts_immutable before update or delete on forecast_receipts
for each row execute function reject_immutable_mutation();

commit;
