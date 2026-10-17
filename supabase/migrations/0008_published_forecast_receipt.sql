begin;

alter table market_forecast_history
  add column if not exists receipt_json jsonb;

comment on column market_forecast_history.receipt_json is
  'Immutable forecast receipt committed with the published history point.';

commit;
