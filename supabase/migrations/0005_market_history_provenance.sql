begin;

alter table market_forecast_history
  alter column simulation_artifact_id drop not null;

alter table market_forecast_history
  add column source_kind text not null default 'published_forecast'
  check (source_kind in ('published_forecast', 'synthetic_demo'));

comment on column market_forecast_history.source_kind is
  'Explicit provenance: real published forecasts or deterministic synthetic demo history.';
comment on column market_forecast_history.simulation_artifact_id is
  'Legacy optional receipt link. What If simulations never create market history.';

commit;
