# Chart, radar, and reliability audit

Base: Pass 9A PR #35 (`fcf09be`). This follow-up does not change published receipts,
statistical coefficients, production evidence, or the What If and Social/Profile designs.

## Findings

| Severity | Location | Reproduction and root cause | User impact | Fix or recommendation | Test | Limit |
| --- | --- | --- | --- | --- | --- | --- |
| P0 | `apps/web/src/api/client.ts` optional continuation request; `apps/web/src/pages/GoalDetailRoute.tsx:91` and `EvidenceRoute.tsx:67` | **Confirmed in signed-in production browser:** the FDE goal displayed a historical chart and “Status unavailable.” An isolated API test confirms `GET /goals/{id}/evidence/continuation` returns 404 when a goal has no creation workflow; the generic client treated this optional absence as an error and the route suppressed current odds. The production response code itself was not captured. | Valid published odds can be hidden behind a false status failure. | Treat 404 as `null` only for this optional query; retain errors for other status codes. Routes then derive status from the goal and immutable history. | `client.chartAudit.test.ts`; `test_chart_status_audit.py` | Post-fix production browser verification requires deployment; this audit branch is not deployed. |
| P1 | `apps/api/src/personal_markets/remote_mcp/odds_app.py:126-155` | **Confirmed in DOM harness:** any unrelated MCP result carrying `status` was accepted as chart data and replaced 18 published points with an empty series. Late responses from a previous goal could also replace the active chart. | MCP Apps chart intermittently showed “Not priced” despite valid receipts. | Accept only goal-bound payloads with `points`; guard goal switches, sort and validate points, deduplicate receipt IDs, preserve the chart through unrelated/error notifications. | `test_remote_mcp_odds_app_runtime.py` | ChatGPT host notification behavior remains unverified; this is a real DOM + host-message simulation. |
| P1 | `apps/api/src/personal_markets/remote_mcp/tools.py:665-707` | **Confirmed by MCP harness:** `get_forecast` returned the old historical probability as current after `last_publication.status=withheld`. | Agents could report stale odds as current. | Return `WITHHELD` with null current probability, preserve history and receipt identity in history/chart, and label the chart as historical. | `test_chart_status_audit.py` | Pending/failed creation states from the workflow store are not yet joined into MCP current status. |
| P1 | `apps/api/src/personal_markets/profile/parameters.py:145-224` | **Confirmed by fixture and API test:** canonical dated `applications_submitted` increments did not match the radar's `applications_per_week` period metric. Similar activity-only gaps affected study, running, and contributions. | Authentic activity could leave measured axes blank. | Derive bounded rolling values from dated increments with exact metric/unit checks, while retaining reported period values as distinct readings. No odds coefficient changes. | `test_measured_parameter_profile.py`; `test_chart_status_audit.py` | The rolling total reflects submitted observations, not all activity a user may have performed. |
| P1 | `apps/web/src/adapters/marketViewModel.ts:22-27`; `apps/web/src/features/goals/marketViewModel.ts:26-34` | **Confirmed by static inspection:** frontend adapters preserve API order and convert invalid dates to `NaN`; no sorting or validation precedes chart geometry or range filtering. | Out-of-order or undated receipts can break chart display or select the wrong current point. | After frontend ownership is clear, filter finite probabilities and valid timestamps, sort by publication time with receipt ID tie-break, and distinguish missing date from empty history. | None added here; frontend change deferred. | Database query currently orders by `created_at`, reducing but not eliminating malformed/legacy row risk. |
| P1 | `apps/web/src/features/goals/EvidenceWorkflow.tsx:33-36,52-55`; `MarketsRoute.tsx:14-25` | **Confirmed by static inspection:** evidence success invalidates detail queries but not the `goals/dashboard` query that powers Market cards; dashboard has a 60-second stale window. | Market cards can show older odds after evidence publishes. | Invalidate `['goals','dashboard']` after successful evidence completion and publication; preserve previous data only with a visible refresh state if desired. | Deferred to frontend owner. | Source-workspace completion already invalidates dashboard. |
| P2 | `apps/web/src/components/market/MarketDetailPage.tsx:112-117` | **Suspected:** chart selection is component state and is not reset when a route reuses the component for a different goal. | Previous goal's selected odds may briefly appear over a new goal. | Reset selection on `market.id` change or key the chart component by goal ID. | Needs browser test. | Not observed in this browser session. |
| P2 | `apps/web/src/components/market/WealthsimpleAreaChart.tsx:385`; chart CSS | **Unverified:** zero-width `ResponsiveContainer`, clipping, mobile, and dark-mode concerns were inspected statically but not reproduced. | Could suppress or clip a valid chart. | Add viewport browser tests after frontend branches converge; avoid CSS changes without a reproduction. | None. | Live session verified a desktop light-mode chart only. |

## Receipt and state path

`market_forecast_history` is the immutable source for website history and MCP chart
points. The website's `/api/v1/what-if/history/{goal_id}` DTO carries probability,
receipt ID, source kind and `created_at`. The dashboard batches the same owner-scoped
histories with creation status. Current publication state is separate from historical
availability: an older `EXPLORATORY` contract or `NEEDS_INPUT` specification does not
erase a published receipt, while a later withheld publication must hide *current* odds.

The MCP chart accepts only published, dated, finite probabilities. An undated or invalid
receipt is retained in forecast history but cannot be placed on a time axis. That case
now reports chart history unavailable instead of claiming no receipt exists. The static
PNG is generated from the same filtered series and has no public URL. The embedded
MCP Apps resource receives structured content through host messages; local tests verify
initial, repeated, unrelated, late and goal-switch messages. They do not establish
ChatGPT host rendering or tool-result delivery.

## Authentic radar data and model impact

`GET /api/v1/profile` selects only the principal's goals and committed evidence,
excluding recognized synthetic fixture rows. `ParameterRadar` consumes the returned
`radar.parameters`; `ExecutionProfileRadar` consumes separate behavior estimates.
Neither radar's display normalization is a forecast coefficient.

Savings measurements require a recognized currency code; mixed currencies are withheld
instead of converted. The current recognized-code set is explicit and can be extended
after a unit contract is added. Measurement units such as `hrs/month` cannot pass as
currency.

For historical backfill, the supported route is an owner-authorized evidence workflow
with explicit metric, value, unit, observation kind and actual `observed_at`; the user
must review and confirm it. Dated application counts, practice/study hours, running
distance and financial contributions can now populate matching Profile axes. The
existing evidence service assigns self-reported or agent-reported provenance and
deduplicates submissions; user input must not be labeled provider verified. The API
test commits an agent-reported application increment, refetches Profile, confirms the
value, retries idempotently, and checks a second owner sees no value. No real account
was backfilled in this audit.

Some of these metrics are also read by existing model families: applications by the
hiring funnel, monthly contributions by finance, and weekly distance by running.
Study/practice hours are tracked by the hiring feature builder, but an observed
association is not a licensed causal probability effect. Reading minutes populate a
Profile axis but need not move goal odds. No coefficient was added. The current
running builder uses the latest `weekly_distance_km` reading rather than the radar's
rolling sum of distance increments; treat those as different measures until a model
contract explicitly reconciles them. Formal correction/retraction semantics for
previously committed observations need a separate evidence contract; this audit does
not silently delete or rewrite receipts.

## Verification boundary

The signed-in production browser reproduced the FDE “Status unavailable” headline
beside a visible historical chart before this branch's client fix. No production
write or deployment was performed. The FDE 76.46% / 18-point case was also modeled
as an isolated regression fixture; the live receipt count and exact value were not
queried from production. DOM and MCP SDK tests are identified as harness tests, not
ChatGPT host acceptance. Mobile, dark mode, and post-deployment browser acceptance
remain open.
