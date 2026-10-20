# Improvement Changelog

This file is both an engineering log and a hackathon deliverable.

## 2026-10-19 — Pass 06: private staging packaging; live agents blocked on hosting

**Hypothesis:** Existing FastAPI `/mcp`, Clerk, and migrations `0001–0015` can be packaged as one single-worker HTTPS staging stack without copying the local database or weakening OAuth, and real ChatGPT Plus / Grok Bot can then be connected.

**Changes:** Dockerfile (one Uvicorn process + migrate-on-boot with `schema_migrations` tracking), `render.yaml`, `vercel.json`, `.env.staging.example`. DCR redirect URI cap 5→16; Cursor `cursor://` native callback allowed for Grok Bot DCR; still reject `javascript:`/`data:`/`file:` and non-loopback http. Blank `PM_CORS_ORIGIN_REGEX` disables the localhost regex. `HOST`/`PORT` read from the environment. No new product UI, no new forecast engine, no numbered migration `0016`. Local development `postgres` was not reset; `schema_migrations` was recorded there so re-migrate skips. Isolated `playitout_pass06_test` applied `0001–0015` from empty.

**Measured result:** Backend `502 passed, 4 skipped`. Isolated Postgres integration `10 passed`. Vitest `33`. Playwright Odds Explorer `2/2` (mocked auth). Architecture and migrations passed. Linked Supabase `klcqvxhemrirjixherkl` SQL timed out. No Render/Vercel project was created from this session. ChatGPT Chat, ChatGPT Work, Grok Bot, live Clerk A/B/C, Gmail handoff: **BLOCKED**. No invented staging URLs. No paid eval scripts.

**Artifacts/run IDs:** `docs/final/reports/PASS_06_RESULT.md`, `docs/final/reports/CLIENT_CAPABILITY_MATRIX.md`.

## 2026-10-18 — Pass 05: local MCP capability parity and Odds Explorer

**Hypothesis:** The same authenticated user can complete goal creation, evidence, historical odds, What If, and chart retrieval from a local MCP client without duplicating services or inventing history, if we extend the existing `/mcp` adapter and extract the Wealthsimple chart.

**Changes:** Nine tools on the existing OAuth `/mcp` connection (`create_goal`, `continue_goal_creation`, `compare_forecasts`, `compare_scenarios`, `submit_structured_rows`, `submit_table_text`, `submit_file_bytes`, `show_odds_chart`, `get_odds_chart_image`). Goal Architect continuation without phantom goals. As-of comparisons in percentage points on published receipts. What If remains hypothetical. Bounded structured/file handoff (no URL fetch). Reusable Odds Explorer on Goal Detail (`1D/1W/1M/1Y/ALL`). MCP Apps `ui://playitout/odds-explorer` plus static PNG. No migration. No cloud.

**Measured result:** Backend `498 passed, 4 skipped`. Vitest `33`. Playwright Odds Explorer `2/2` (auth-bypass, mocked API). Architecture and migrations (15 files) passed. MCP Apps exercised via official SDK initialize/resource/tool-meta only. ChatGPT/Grok interactive UI **NOT VERIFIED**. No paid inference in this pass.

**Artifacts/run IDs:** `docs/final/reports/PASS_05_RESULT.md`, `docs/final/reports/LOCAL_AGENT_ACCEPTANCE.md`, `docs/final/reports/odds-explorer-desktop.png`, `docs/final/reports/odds-static.png`.

## Submission-stage summary

### BIGGEST CONTRIBUTOR

Moving probability ownership from raw GPT output to versioned numerical forecasting and calibration was the largest measured contributor: education Brier moved from GPT-5.4 `0.223` to Play It Out `0.158`, and the final four-domain macro was `0.132` to `0.110`.

### REMOVED EXPERIMENTS

Behavior logistic refinement was rejected for overfit; weak/non-improving decay settings were not selected; deterministic/regex semantic routes were removed or demoted; and fixture-generated Compare/Futures/Paths clouds were removed from production. Their measured evidence and next decisions remain in the table and dated entries below.

| Stage | What we tried / why | Evidence | Decision / learning |
|---|---|---|---|
| Baseline | Raw GPT predicts odds and action effects directly | `hackathon_proof_v1/results.json` | Rejected as authority: it produced probability claims and numerical uplift without a calibrated basis |
| Goal Contract | Structured Goal Architect output makes outcomes measurable | agent eval and trajectory artifacts | Kept; clarification/HITL is required for underspecified intent |
| Numerical forecasting | Move final probability ownership from LLMs to versioned numerical models | OULAD and proof-v2 pricing artifacts | Kept; this is the core safety/measurement boundary |
| Temporal evidence / decay | Use only evidence available at each checkpoint and test recency weighting | OULAD manifest/results; running-volume proof | Kept leakage controls; rejected decay settings that did not improve held-out performance |
| Model registry | Route by goal shape and cap supported status | model registry tests and receipts | Kept; unsupported shapes must remain exploratory/unpriced |
| Monte Carlo + CRN | Compare interventions with deterministic RNG and common random numbers | Monte Carlo/CRN proof artifacts | Kept for variance-reduced model-consistent comparisons |
| Goal Architect / Evidence / Source Planner | Separate semantic contracting, normalization, and dynamic resource selection | agent eval v1/v2 | Kept; deterministic regex/provider maps were removed or demoted |
| Intervention Agent | Map actions to mechanisms/known state, not arbitrary uplift | live ablation and proof v1 | Kept fail-closed behavior; unsupported numerical effects remain unpriced |
| Research + provenance | Attach supplied-source claims and evidence strength | live workflow, GitHub forecast receipt | Kept; association is not promoted to causation |
| Forecast Critic | Veto leakage, invalid values, unsupported coefficient provenance | critic eval rows | Kept; critic cannot replace the numerical probability |
| Composio MCP evidence | Discover exact connected providers/resources and preserve raw records | connector tests and Pass 6 ledger | Kept with OAuth and connection truth surfaced |
| Exact resource evidence | Rank pages/repos/calendars instead of provider stereotypes | resource suite: top-1 79%, NDCG@5 0.97 | Kept; unrelated resources rank low |
| Behavior/execution probability | Separate plan quality from probability an action is executed | behavior benchmark | Kept as an explicit multiplier, not an LLM coefficient |
| Compare/Futures/Paths fixture removal | Remove production reliance on seeded scenario clouds | Pass 6 tests/browser evidence | Removed fixture paths from production; demo-only data remains labeled |
| Priceability + missing state | Surface what can/cannot be priced and why | unseen-goal and What If artifacts | Kept; missing state yields a recipe or withholding |
| REMOVED: behavior logistic refinement | Extra behavior model complexity overfit | recorded behavior evaluation entries below | Rejected; retained the simpler validated behavior path |
| REMOVED: non-improving decay | Alternate decay configuration failed held-out improvement | OULAD/running experiments below | Rejected; no claimed gain |
| REMOVED: deterministic/regex semantics | Hard-coded intent/provider routes looked good on fixtures but did not generalize | expanded arbitrary-goal/resource cases | Removed or demoted to validation/fallback only |
| REMOVED: fixture simulation clouds | Production Compare/Futures/Paths could display seeded curves | Pass 6 implementation/tests | Removed from production paths |
| REMOVED: losing model families | Candidate models/configurations that lost validation | append-only experiment entries below | Not selected; historical results preserved |
| Final | Full goal→evidence→forecast→What If→optimization product | `docs/PASS_6_EXECUTION.md`, proof v2, submission package | Ship the bounded agent/numerical system; retain stated limitations |

This table is an index. The dated entries below are the authoritative measured record and include failed approaches without rewriting historical results.

## 2026-10-18 — Pre-deployment E2E (Phases 0–4): stabilize, do not add features

**Hypothesis:** A full acceptance pass on an isolated DB would either prove the product ready for staging or surface engine/auth/MCP defects that unit tests missed. No new product surface. `$100` Spur cap still not implemented.

**Changes:** Isolated `playitout_e2e` + API `:8030`. Fixes only where E2E failed: hiring zero-counts; Architect `current_state_known` JSON Schema; stock aliases vs rate labels; half/full marathon distance; DAG milestone targets; unmapped What If not persisted; running trend assumption range; Spur JSON-mode extra keys; DAG vs funnel override; categorical launch + mixed metric names; jsonb `Infinity` receipts. Playwright settings tests mock `/api/v1/mcp/**` so Personal agents live regions do not steal status/alert locators.

**Measured result:** Backend `469 passed, 4 skipped`. Vitest `24`. `tsc` clean. Live scenarios A/B/C/E priced; D priced at `0.200` after alias/launch fixes and API restart. MCP OAuth+PKCE E2E 12/12 checks. Playwright foundation+settings 6/6. Two real Clerk Google sessions **NOT VERIFIED**. Hosted ChatGPT/Claude/Grok MCP **DEFERRED TO STAGING**. Verdict in `docs/PRE_DEPLOYMENT_E2E_REPORT.md`: **NOT READY FOR STAGING**.

**Artifacts/run IDs:** `docs/PRE_DEPLOYMENT_E2E_REPORT.md`, `.artifacts/e2e/scenario_results.json`, `.artifacts/e2e/phase4_mcp_e2e.json`, `.artifacts/e2e/junit_full.xml`.

## 2026-10-18 — Phase 3 reliability: durable uploads, MC frequency, budget inspection

**Hypothesis:** Upload metadata and bytes can survive API restart in owner-scoped Postgres without ephemeral disk; sequential DAG prices should be empirical Monte Carlo frequencies with sampling error, not a silent `1e-6` floor; hosted global spend is already a lifetime counter at `$25`, not a tested `$100` Spur cap.

**Changes:** Migrations `0013`+`0014` applied to development `postgres` and `playitout_phase0_test`. `PostgresUploadStore` holds `bytea` blobs, live SHA-256 uniqueness, 5 MB/50 MB limits, soft-delete, advisory-lock dedupe. `monte_carlo_frequency` reports `p_hat`, binomial SE, Wilson 95% interval, `theoretical_floor=None`, convergence flags; DAG/sequential paths disable the analytical clip. FastAPI restarted against `127.0.0.1:54322/postgres`. No Phase 4 work. No `$100` cap code.

**Measured result:** Backend `365 passed, 4 skipped`. Frontend vitest `22 passed`; `tsc --noEmit` clean. Zero-success DAG `p_hat=0` (2000 draws), not `1e-6`. Postgres upload tests cover restart (new engine), cross-tenant denial, delete/reimport, concurrent ingest. Authenticated Clerk browser E2E **NOT VERIFIED** (Sign in only). Global hosted quota is lifetime cumulative in `hosted_budget_counters`; daily `openai_max_cost_usd` is a separate reset. `$100` Spur cap **not implemented** and not claimed.

**Artifacts/run IDs:** `docs/PHASE3_ENGINEERING_REPORT.md`, `supabase/migrations/0014_goal_upload_blobs.sql`, `apps/api/src/personal_markets/forecasting/monte_carlo.py`, `apps/api/tests/test_phase3_postgres_uploads.py`.

## 2026-10-18 — Phase 3 composed primitives instead of one-model-per-goal-type

**Hypothesis:** Distinct measurable goals can share a versioned ForecastSpec compiler and registered primitives (count, growth, funnel, hazard, threshold, DAG) without replacing working hiring/running/startup/finance adapters, and without an LLM assigning the probability.

**Changes:** Additive ForecastSpec v2 plus `composed_v1` compiler; Goal Architect refinement selects a primitive or keeps a domain adapter; evidence aliases and snapshot/increment/period semantics generalized; owner-scoped CSV/XLSX/PDF uploads; frozen-reference research can fill a parameter only when marked applicable and `used_by_engine`; generic What If maps interventions onto composed parameters or returns unmapped `NOT_PRICED`. Frontend keeps the existing Markets/Evidence/What If shell and adds dataset mapping plus a compact model note.

**Measured result:** Backend `358 passed, 4 skipped`. Frontend vitest `22 passed`. Synthetic Poisson survival and log-linear growth unit tests match library formulas. Example composed prices on toy histories: subscribers growth ≈ `1.6e-5` (log-linear), travel count ≈ `0.13%` (Poisson with rate uncertainty), launch→customers→MRR waiting-time MC ≈ `1e-6` (clip; remaining MRR gap is not reachable in a ~200-day horizon). No new held-out Brier/log-loss run; these are mathematical correctness tests, not empirical calibration. A $100 cumulative Spur cap is **not** implemented; hosted defaults remain `$2` per user and `$25` global.

**Artifacts/run IDs:** `docs/PHASE3_ENGINEERING_REPORT.md`, `apps/api/tests/test_phase3_*.py`, `supabase/migrations/0013_goal_uploads.sql`.

## 2026-10-17 — Invite URL session memory and Clerk azp fixtures

**Hypothesis:** Hash-only invitation storage cannot recover plaintext links after create, so Settings must keep newly generated URLs in browser memory. Clerk enforcement is only proven if correctly signed tokens with an unauthorized `azp` are rejected after signature/issuer/exp verification, including when `aud` would otherwise satisfy PyJWT.

**Changes:** Create still returns the token once. `GET /api/v1/admin/invites` and revoke return `InvitationHistory` without a token field. Settings keeps invitation_id→URL while the page is open, with Copy, a reload warning, Generate replacement (revokes then issues a new link), and Revoke. Clerk verifier still uses RS256 JWKS, issuer, exp, `verify_aud=False`, then allowlists cryptographically verified `azp` against `PM_CLERK_AUTHORIZED_PARTIES`.

**Measured result:** Signed JWT fixtures against a trusted test JWKS: allowed `azp` without `aud` accepted; unauthorized `azp` (with and without valid `aud`) 401 after successful signature verify; tampered signature and expired tokens 401 for distinct reasons. Invitation history JSON omits `token`. No new held-out Brier/log-loss run.

**Artifacts/run IDs:** `apps/api/src/personal_markets/identity/tokens.py`, `apps/api/tests/test_clerk_jwt.py`, `apps/api/tests/test_phase1_auth.py`.

## 2026-10-17 — Admin lockout: Clerk azp vs JWT aud

**Hypothesis:** A successful Clerk Google session still 401s `/me` if FastAPI treats `PM_CLERK_AUTHORIZED_PARTIES` as JWT `aud`. Clerk session tokens put the app origin in `azp` and often omit `aud`, so PyJWT rejects a valid token. AuthGate then treats a missing `/me` payload as “uninvited.”

**Changes:** Verify RS256 with `verify_aud=False` and allowlist `azp`, treating `localhost` and `127.0.0.1` as equivalent. Admin role is computed only from a verified Clerk email on `PM_ADMIN_EMAILS` (JWT `role` ignored; missing email loaded via Clerk Backend API). Allowlisted admins reach invitation management with zero invitations and without hosted entitlement. Auth screens reuse Play It Out type, color, and controls.

**Measured result:** Regression tests only (admin bootstrap, spoofed role ignored, unverified allowlisted email is not admin, azp accepted without aud). No new held-out Brier/log-loss run.

**Artifacts/run IDs:** `apps/api/tests/test_phase1_auth.py`, `apps/web/src/auth/AuthGate.tsx`.

## 2026-10-17 — Shared multi-use hackathon invitations

**Hypothesis:** A single hashed invitation token with a row lock, a `(invitation_id, user_id)` redemption table, and idempotent entitlement grants can let up to 20 distinct Clerk accounts use one link without double-counting slots or hosted quota, while email-bound single-use invites stay unchanged.

**Changes:** Invitations gained `max_redemptions` / `redemption_count` and `invitation_redemptions`. Shared links default to 20, expire, and revoke. The same Clerk account redeeming twice returns access without incrementing again. Uninvited accounts remain blocked from private APIs and hosted inference. Settings adds an admin generate/copy/count surface. Clerk continues to use `VITE_CLERK_PUBLISHABLE_KEY` on the Vite app (env loaded from the repo root) and `PM_CLERK_JWKS_URL` / `PM_CLERK_ISSUER` for FastAPI RS256 verification. Google remains a Clerk Dashboard SSO connection; `CLERK_SECRET_KEY` is not used for JWT verify and must not be `VITE_`-prefixed.

**Measured result:** Regression tests only (email-bound single-use preserved; shared cap, idempotent re-redeem, concurrent slot consume, uninvited 403). No new held-out Brier/log-loss run.

**Artifacts/run IDs:** `supabase/migrations/0010_shared_invitations.sql`, `apps/api/tests/test_phase1_auth.py`, `apps/api/tests/test_postgres_integration.py`.

## 2026-10-17 — Phase 0 snapshot vs increment aggregation

**Hypothesis:** Treating every `applications` observation as an additive event makes restated stocks sum (6 then 18 → 24), while timestamp-free fingerprints collapse legitimate same-value increments in different periods.

**Changes:** Evidence ingest now distinguishes absolute snapshots, dated increments, and period measurements. Hiring aggregation takes the latest snapshot and only adds increments after it. Identical increments on different days keep separate fingerprints. Cross-source duplicates of the same stock remain one row and record corroborating provenance. Public `GET /health` returns status only; database host/name is `GET /health/details` in non-production.

**Measured result:** Regression tests only (hiring 6→18 prices as 18, not 24; period increments persist; provenance retained). No new held-out Brier/log-loss run.

**Artifacts/run IDs:** `apps/api/tests/test_evidence_metrics.py`, `test_hiring_model.py`, `test_manual_evidence_api.py`, `test_api.py`.

## 2026-08-30 — Composio auth launcher (about:blank)

**Hypothesis:** `window.open("about:blank", "_blank", "noopener,noreferrer")` returns a null/unusable WindowProxy, so the async callback cannot navigate the tab.

**Changes:** Synchronously open same-origin `/auth/composio/launch?id=…`. Deliver `auth_url` via `postMessage` + BroadcastChannel + localStorage. Launcher executes `location.replace(authUrl)`. Manual link remains fallback.

**Measured result:** Playwright desktop: Notion, Gmail, Google Calendar, Slack auth initiation leave the launcher and reach `connect.composio.dev` or the provider OAuth host (not `about:blank`). GitHub connect stays idempotent ACTIVE. Popup-blocked and 500-connect paths show the manual link / visible error.

**Artifacts/run IDs:** `apps/web/src/features/plugins/composioAuthLaunch.ts`; `ComposioAuthLauncherPage.tsx`; `e2e/plugins.spec.ts`.

Do not backfill a fake story after the project is finished.

## 2026-08-30 — Running pace-improve bench + model-consistent action policy v2

**Hypothesis:** A second Figshare running contract (H1→H2 pace improve ≥5%) and an expanded multi-action What If ranking grid strengthen product proof without touching the frozen volume shared-subset (where GPT edged PIO) or inventing causal ATEs.

**Changes:**
- Added `running_pace_improve_2019_v1` (prediction 2019-06-30; features weeks ≤ t only; athlete-disjoint SHA256 `20260830`; eligibility distance>0 both halves).
- Ran prepare + statistical baselines (prevalence / logistic / HGB).
- Wrote `benchmarks/hackathon_proof_v2/action_policy_results.json` via `scripts/eval_action_policy_v2.py`: greedy vs equal vs random vs oracle under the hiring numerical simulator with direct `parsed_changes` (NON-CAUSAL / MODEL-CONSISTENT). No RCT ATE; OULAD VLE associative proxy skipped (full `studentVle.csv` not under `data/`).
- Left `benchmarks/running_volume_2019_v1/*` byte-identical (GPT shared-40 win preserved).

**Measured result:** Pace improve n=34,122 athletes (test 3,433); base rate ≈13.5%; HGB Brier `0.095` vs prevalence `0.119` (AUC ≈0.825). Action policy (36 rate×scale×budget cases, NON-CAUSAL): greedy top-1 `8%` (efficiency vs absolute-best), equal-proxy `36%`, random `19%`; mean upside captured greedy `95%` / equal `55%` / random `73%`; mean regret vs oracle greedy `0.009` / equal `0.142` / random `0.041`. Oracle best-action mix: applications=23, response_rate=13.

**Artifacts/run IDs:** `benchmarks/running_pace_improve_2019_v1/`; `benchmarks/hackathon_proof_v2/action_policy_results.json`; scripts `prepare_running_pace_improve.py`, `eval_action_policy_v2.py`.

Do not backfill a fake story after the project is finished.

## 2026-08-30 — Expand frozen agent eval cases (structural labels only)

**Hypothesis:** Broader hand-authored Goal Architect / Source Planner / intervention / resource-level cases improve coverage without inventing measured uplifts or hardcoding domain product branches.

**Changes:**
- Appended ~20 Goal Architect intents (promotion, GPA, cert, half marathon, emergency fund, debt, MRR, enterprise customer, newsletter, piano, reading, bench, plus clarify variants) to `pass6_eval_v1/cases.json` and `hackathon_proof_v2/agent_cases_v2.json`.
- Added 13 resource-level Source Planner scenarios (Notion pages / Sheets tabs / GitHub repos / Calendar) with relevance labels.
- Expanded What If interventions (promotion plan, open source, rent reduction, intervals, raise prices, publish 2×/week, enterprise outreach, piano, reading).
- Scripted `fake_inference` clarify markers + resource ranking path; `agent_eval.evaluate_source_planner_resources` reports top-1 / precision@K / NDCG vs frozen labels.

**Measured result:** Scripted pytest only (`test_agent_eval.py` passed). No live GPT numbers claimed.

**Artifacts/run IDs:** `benchmarks/pass6_eval_v1/cases.json`; `benchmarks/hackathon_proof_v2/agent_cases_v2.json`; counts GA 85 / interventions 47 / SP 33 (resource_level 13) / evidence 32 / critic 16.

Do not backfill a fake story after the project is finished.

## Pass 6 proof v2 — multi-domain resolved pricing

**Change:** Stopped treating OULAD as the only product-wide proof. Loaded real public panels for career (JTH Zenodo 21390581), finance (Fed SHED 2022→2023 shedid panel), and running (Figshare training volume 2019), kept OULAD education, ran fair GPT-5.4 shared-subset pricing with identical features, and shipped judge translations + `benchmarks/hackathon_proof_v2/`.

**Measured result (shared GPT comparison):** Macro Brier GPT `0.132` → PIO `0.110` (**16.5%** lower macro probability error); PIO won **3/4** domains. Education kept −29.1% (0.223→0.158). Finance −12.9% (0.192→0.167, n=40). Career tiny Brier edge with AUC 0.66→0.73 (rare offers). Running March shared-40: **GPT won** near-ceiling volume task (0.011 vs 0.014) — reported honestly. Full-test statistical: SHED HGB Brier 0.130 (n=374); running volume HGB 0.062 (n=10932) with Mar→Sep error drop; JTH HGB Brier ~0.020 / AUC ~0.70 on ~2% offers. Decay on running volume ~0.3% — not claimed. Habits/startup/causal RCT panels not loaded (download blocks / weak candidates). Agent frozen sets expanded (GA 65 / evidence 32 / SP 20 / intervention 38 / critic 16).

**Artifacts/run IDs:** `benchmarks/hackathon_proof_v2/` (`PROOF_TABLE.md`, `JUDGE_SUMMARY.md`, `pricing_results.json`, `domain_inventory.json`); domain benches `jth_offer_v1`, `shed_emergency_savings_v1`, `running_volume_2019_v1`.

Do not backfill a fake story after the project is finished.

## Pass 3 validation — live runtime and shared subset

**Change:** Ran the configured OpenAI/LangGraph/Postgres product path and added a fair shared-200 replay for the official GPT-5.4, logistic, and selected Pass 2 systems. Live validation exposed and corrected two boundary/telemetry defects: defaulted non-null structured fields were incorrectly nullable in the OpenAI schema, and per-AgentRun estimated cost was recorded as zero.

**Measured result:** Live workflow withheld the uncalibrated career goal after 21.822 s, 7,760 tokens, and $0.021388 estimated cost, with zero retries and no duplicate goal/evidence side effects. Shared-200 Brier: GPT-5.4 `0.2227995`, logistic `0.1729642`, selected Pass 2 `0.1579936`. The full 13,252-row Pass 2 metrics remain unchanged.

**Artifacts/run IDs:** `benchmarks/agent_runtime_validation_v1/live_workflow_20260829.json`; `benchmarks/oulad_completion_v1/shared_200_comparison_v1.json`; goal thread `bfba9666-ce78-42e3-822c-388f0b3a8be2`; evidence thread `81fc66e6-04b2-4866-bcd9-9b91e2979d67`.

Do not backfill a fake story after the project is finished.

## Rules

For every meaningful experiment:
- use the same frozen evaluation protocol where possible
- record the run/artifact ID
- record the metric
- explain why the change was tried
- decide keep/revise/remove
- preserve failures

Primary metric: **Brier Score (lower is better).**

---

| Stage | What we tried and why | Evidence / metric | Decision / learning | Run ID |
|---|---|---|---|---|
| Baseline | General-purpose LLM (`gpt-5.4`) with the frozen OULAD checkpoint schema. Establishes the starting point required by the hackathon. | 200-case frozen test subset Brier `0.22280`; estimated cost `$0.47`, actual `$0.2696`. Full test partition was not scored because of the `$5` guard. | Keep as official LLM baseline only. Not a production model. Worse than the Pass 2 numerical core on this subset. | `openai_probability_baseline_v1` |
| Iteration 1 | TBD | TBD | TBD | TBD |
| Iteration 2 | TBD | TBD | TBD | TBD |
| Iteration 3 | TBD | TBD | TBD | TBD |
| Final | Combination of only the changes that survived evaluation. | TBD | TBD | TBD |

## Pass 2 measured experiments — `oulad-heldout-20260828`

All selection figures below use the frozen validation partition; final figures use the untouched
test partition (2,922 students, 13,252 checkpoint forecasts).

| Experiment | Hypothesis/configuration | Brier and runtime | Decision |
|---|---|---|---|
| Prevalence | Constant train+validation completion rate is the minimum sanity baseline. | Test Brier `0.24933`; negligible inference time. | Keep as reference floor. |
| Logistic + 7/14/28-day decay | A regularized linear probability ranking should be hard to beat and reveal whether decay matters. | Validation Brier values are recorded in `evaluation_results.json`; selected final configuration test Brier raw `0.15073`, calibrated `0.15004`. | Keep as statistical baseline. |
| Histogram gradient boosting + 7-day decay | Nonlinear interactions may improve probability quality. | Validation Brier recorded; not the best after temporal feature expansion. | Remove this half-life. |
| Histogram gradient boosting + 14-day decay | Two-week memory may balance recent deterioration and established trajectory. | Best validation configuration; test Brier raw `0.13786`, calibrated `0.13783`; fit/predict about 2 seconds on this machine. | Keep as final. |
| Histogram gradient boosting + 28-day decay | Longer memory may stabilize sparse activity. | Validation Brier recorded; lost to 14 days. | Remove this half-life. |
| Platt vs isotonic calibration | A held-out monotone mapping should reduce probability error. | Final model selected Platt and improved test Brier slightly; logistic selected isotonic. Exact calibration metrics/bins are frozen in the result JSON. | Keep separately versioned mappings. |
| Explicit latent/HMM model | A latent regime model might distinguish one bad day from persistent decline. | Not executed: controlled EWMA/window/streak summaries represent the failure mode without evidence that HMM complexity is justified. | Do not add. |

The final-versus-logistic paired student bootstrap mean Brier improvement is `0.01219`, with 95%
interval `[0.01012, 0.01427]` across 2,000 resamples. This is stable on this frozen benchmark but
is not evidence of transportability or causal effects.

## Foundation: reproducible evaluation boundary

**Date:** 2026-08-28
**Hypothesis:** A provider-neutral, fail-closed harness is necessary before any baseline request so cases, metrics, and raw predictions cannot drift between systems.
**Change:** Added versioned evaluation contracts, known-value metric tests, paired comparison, OULAD schema validation, and a CLI that refuses to emit predictions while unconfigured.
**Evaluation protocol:** Infrastructure-only; no forecast systems were executed.
**Primary metric before:** TBD
**Primary metric after:** TBD
**Decision:** Keep
**Why:** This establishes the frozen measurement boundary without making an unsupported performance claim.
**Artifact/run IDs:** No evaluation run created.

---

## Pass 3 — agent runtime (structured workflow vs raw LLM)

**Date:** 2026-08-29
**Hypothesis:** Structured outputs + deterministic validation + a critic that cannot edit probabilities will reject bad artifacts that a raw JSON blob would accept, without inventing odds.
**Change:** LangGraph product-agent graph, OpenAI Responses structured outputs, Goal Architect / Evidence / Research / Critic, GitHub + CSV + manual evidence, frozen research provider.
**Evaluation protocol:** Deterministic scripted-provider suite in `npm run evaluate:agents`. Live OpenAI is not required and was not used to fill this table.
**Cases/split:** 25 Goal Architect intents, 10 Evidence texts, 5 Critic defect injections.
**Primary metric before:** n/a (agents did not exist)
**Primary metric after:** Goal Architect 25/25 schema-valid, 23/25 clarification routing correct (1 unnecessary, 1 missed on scripted stand-in). Evidence 10/10 schema and event counts. Critic 5/5 injected defects, 0 false vetoes.
**Secondary observations:** Official LLM probability baseline is a separate command (`evaluate:openai-baseline`) and is not a product-agent score.
**Latency/cost change:** Scripted eval has negligible cost. Live agent cost is usage-logged per run.
**Unexpected failures:** Record only after the eval command is executed; do not backfill.
**Decision:** Keep
**Why:** The workflow matches the architectural invariant that LLMs never emit the published probability.
**Next experiment:** Pass 4 What If / action ranking on top of this graph.
**Artifact/run IDs:** `benchmarks/agent_eval_v1/results.json`, `benchmarks/agent_trajectories/representative.json`

---

## Pass 3 — official LLM probability baseline

**Date:** 2026-08-29
**Hypothesis:** A single general-purpose LLM, given the same frozen OULAD checkpoint features, can produce probabilities, but will not match a calibrated numerical model.
**Change:** Executed `npm run evaluate:openai-baseline` against `gpt-5.4` via the Responses API with strict `{probability}` JSON schema. Cached by case ID + prompt version + model. No logistic substitution.
**Evaluation protocol:** First 200 test-split checkpoint rows after `id_student`, `checkpoint_day` sort. Cost estimate `$0.47` under the `$5` guard; concurrency 4.
**Cases/split:** n=200 frozen OULAD test checkpoints (not the full 13,252-row test partition).
**Primary metric before:** n/a
**Primary metric after:** Brier `0.22280`
**Secondary observations:** Actual estimated API cost `$0.2696`. Pass 2 histogram-gradient-boosting calibrated test Brier was `0.13783` on the full test partition; that is a different coverage and is not a paired comparison.
**Latency/cost change:** ~59s wall clock for 200 cached-or-live calls on this machine.
**Unexpected failures:** None on this run.
**Decision:** Keep as the official hackathon LLM baseline artifact. Do not use it as a product forecast.
**Why:** The required one-model baseline now has a real, inspectable score.
**Next experiment:** Pass 4 What If / action ranking; optional larger LLM subset if budget allows.
**Artifact/run IDs:** `benchmarks/oulad_completion_v1/openai_baseline_result.json`, `.artifacts/openai_baseline_cache/` (local cache, gitignored)


---

# Experiment template

## Experiment: <name>

**Date:**
**Hypothesis:**
**Failure mode observed:**
**Change:**
**Evaluation protocol:**
**Cases/split:**
**Primary metric before:**
**Primary metric after:**
**Secondary observations:**
**Latency/cost change:**
**Unexpected failures:**
**Decision:** Keep / Revise / Remove
**Why:**
**Next experiment:**
**Artifact/run IDs:**

---

# PASS 4 experiments

## 2026-08-29 — PASS 4 seeded paired simulation vertical slice

**Hypothesis:** Common-random-number, vectorized What If simulation can provide stable action
uplift and assumption sensitivity at interactive latency while preserving the semantic-agent /
numerical-model boundary.

**Change:** Added deterministic model-family selection, survival/habit primitives, convergent
continuous/threshold simulation, explicit plan execution uncertainty, sensitivity/fragility,
bounded action enumeration, and a rendered scenario lab.

**Measurement:** Fixed-seed regression tests prove reproducibility and shared-world monotonicity.
The million-dollar demo converged after 6,000 paths with achieved MC SE about 0.64pp; the primary
simulation reported roughly 100ms on the local browser run (sensitivity runs are additional and
vectorized). This is a product-runtime measurement, not a benchmark improvement claim.

**Result:** Accepted as an exploratory product slice. No OULAD benchmark result or historical
measured result was changed.

**Limitations:** Persistence adapter for simulation runs, multi-outcome path comparison UI,
reverse target-probability search, and a full Action Frontier visualization remain follow-up work.

**Next experiment:** Add immutable simulation-run persistence and compare bounded reverse-search
runtime/solution stability across action grids.

**Artifact/run IDs:** Fixed UI/API seed `20260829`; no committed evaluation-run ID.

---

## 2026-08-29 — PASS 4 completion: persistence, reverse search, and decision surfaces

**Hypothesis:** Production-shaped immutable receipts, bounded verified search, and deterministic
critic gates can complete the What If product without adding LLM latency or numerical authority.

**Change:** Added idempotent append-only simulation/history persistence, target search, Pareto
frontier, provenance-gated futures, path comparison, exact numeric inputs, market history, receipt UI,
and deterministic critic withholding.

**Evaluation protocol:** `npm run evaluate:pass4`, seed `20260829`; fixed sanity/known-answer tests,
30 CRN replications, 12 local latency runs (first + 11 assumption reruns).

**Primary metric before:** Pass 3 full flow `21.822s`; no reverse/frontier evaluation.

**Primary metric after:** first What If `30.68ms`; assumption rerun p50 `27.18ms`, p95 `33.95ms`;
optimizer 6/6; reverse search 7/7; deterministic critic avoided 3/4 test-case LLM calls.

**Secondary observations:** CRN variance ratio `0.74931` versus independent simulation; convergence
at 6,000 paths with MC SE `0.006395`; all slider reruns used zero LLM calls.

**Decision:** Keep.

**Why:** The implementation preserves agent/math separation and fails closed when effects or outcome
weights lack provenance.

**Artifact/run IDs:** `benchmarks/pass4_simulation_v1/results.json`, seed `20260829`.

---

## Pass 6 — agentic Intervention + Evidence source architecture

**Change:** Replaced regex-primary What If parsing with bounded **Intervention Agent** (mechanism chain → typed state changes → critic → numerical engine). Added **Goal Source Planner**, goal-specific SyncRecipes, RawSourceRecord→Evidence bridge, automatic sync into Evidence Agent workflow, and Evidence source workspace UI (manual note as fallback tab). What If / Markets UI design unchanged.

**Measured result:** pytest 148 passed (scripted provider); Vitest 13 passed; `verify_intervention_examples.py` — 10/12 example prompts mapped with honest NOT PRICED for hire-salesperson and vague sleep.

**Artifacts/run IDs:** branch `codex/pass-6-end-to-end-product`; `apps/api/scripts/verify_intervention_examples.py`.

---

# Removed experiments

Keep a dedicated section for things we tried and removed.

A removed experiment is valuable if it teaches us something about reliable agentic forecasting.

---

# Candidate final insight — DO NOT LOCK YET

Potential hypothesis to test:

> “LLMs are effective at turning messy evidence into structured context, but unreliable as direct probability calculators; a calibrated numerical forecasting layer improves consistency and probabilistic accuracy.”

This becomes the final hot take only if experiments actually support it.

---

## 2026-08-30 — Pass 6 Composio end-to-end integration layer

**Hypothesis:** A single Composio-backed IntegrationGateway can support hundreds of apps without per-provider backend code; GitHub validates the full evidence → forecast path.

**Changes:**
- `ComposioIntegrationGateway` + `ComposioTransport` + generic normalizer
- Real OAuth connect flow (`pending_auth` → refresh → connected)
- Paginated plugin catalog from Composio toolkits
- Dynamic read capability discovery + `MCPReadPolicy` hardening
- Goal-specific `GoalSyncRecipe` persistence (`0007_goal_sync_recipes.sql`)
- Source Planner + Evidence Agent wired to `mcp_records` (live OpenAI path)
- Plugins/Evidence UI: connect, resource drill-down, recipe approval, sync

**Verified:** pytest full suite; Vitest 13; frontend typecheck/build; live Composio API (catalog + connect link generation); Notion toolkit discovered generically.

**Not verified without user OAuth:** GitHub connected account sync → evidence → forecast on real repo data.

**Removed / avoided:** Per-provider integration classes; fake connected state; mock-only connect in non-test environments.

## 2026-08-30 — Plugins frozen UI + Composio connection reconciliation

**Hypothesis:** Production Plugins should render the approved frozen template DOM/CSS while binding real Composio catalog/connection state; missed OAuth reconciliation should not force re-auth when Composio already reports ACTIVE.

**Changes:**
- `PluginsRoute` is a data wrapper over frozen `PluginsPage` / `PluginDetailPanel` (correct class names: `plugin-search`, `section-heading`, `plugin-list`, `plugin-main`, `connection-state`, `plugin-backdrop`/`plugin-panel`).
- Generic `_reconcile_connections`: list Composio ACTIVE accounts per user, upsert `plugin_connections` with `connected_account_id`, ignore EXPIRED/INITIALIZING, select explicitly when multiple ACTIVE.
- Reconciliation runs on `GET /plugins`, `search_catalog`, and `POST /connect/refresh`.

**Verified:** pytest reconciliation tests; Vitest/typecheck/build; browser Plugins 5173 vs template 5174; live GitHub ACTIVE (`ca_OAMrxROoSCb-`) reconciled without re-OAuth; GitHub E2E sync dedupe on second run.

**Removed / avoided:** Rebuilt Plugins DOM with incompatible classes; treating INITIATED/CONNECTED as connected; local fixture `Set` connection truth.

## 2026-08-30 — Evidence workspace + Composio pagination sync fix

**Hypothesis:** `/sources/sync` 500 was caused by Composio `connected_accounts.list` returning only the first page (GitHub ACTIVE on page 2); dedicated Evidence route improves goal-specific source UX without touching Markets/What If shell.

**Changes:**
- Paginate `list_active_connected_accounts` (cursor loop, limit 50).
- Re-reconcile connection in `sync()` when stored `connected_account_id` exists but local status is `error`.
- Dedicated `/goals/:goalId/evidence` route + polished workspace (recommended / connected / other sections, resource drill-down, manual evidence secondary).
- Plugin `logo_url` from Composio metadata + `PluginBrandIcon` fallback; Plugins connect button hit target + OAuth focus/pending refresh.

**Verified:** pytest 143+ (incl. pagination test); Vitest 13; typecheck/build; ASGI `POST /sources/sync` 200 (was 500); `scripts/pass6_github_e2e.py` double-sync: raw_delta=0, events_delta=0, duplicate_external_ids=0.

**Not verified this run:** Live OpenAI full chain when new GitHub commits arrive; browser screenshots; frozen multi-domain eval ablations; Playwright evidence route E2E.

## 2026-08-30 — Plugin connect + Markets dark mode + connect idempotency

**Hypothesis:** Connect clicks fail because (1) global pending state disabled all plugins, (2) popup blocked after async OAuth, (3) re-connect on ACTIVE GitHub throws Composio multi-account error.

**Changes:**
- `connect_managed` reconciles first; returns connected/pending auth_url without re-initiating OAuth.
- `PluginsRoute`: per-plugin loading, popup-blocked banner with manual auth link, focus/poll refresh.
- `markets.css` + `WealthsimpleAreaChart`: CSS variable tokens aligned with What If dark mode.
- Frozen `benchmarks/pass6_eval_v1/` + `scripts/eval_pass6_suite.py` + `scripts/pass6_full_github_e2e.py`.

**Verified:** pytest full suite; Vitest 13; typecheck; Notion `connect_managed` returns real auth URL; GitHub double-sync dedupe (0 new raw/events/history); connect idempotency unit test.

**Remaining:** Push `PASS6_SYNC_MARKER.md` to GitHub remote for fresh commit ingest; live OpenAI goal/What If browser matrix; full ablation with real GPT baselines.

## 2026-08-30 — Composio popup + intervention thread_id + live verification

**Hypothesis:** Popup must be created synchronously on user click; intervention agent runs must persist UUID `thread_id` values to Postgres.

**Changes:**
- `PluginsRoute`: sync `about:blank` popup → navigate on `auth_url`; blocked-popup fallback link; `isFetching` loading guard; server-search no double-filter in `PluginsPage`.
- `intervention_service.py`: `thread_id = uuid4()` (was composite string → Postgres UUID error).
- `source_api.py`: optional `steps` on recipe save for branch-aware GitHub sync.
- `scripts/pass6_live_verification.py`, `e2e/plugins.spec.ts`.

**Verified:** Playwright plugins 3/3; pytest 152 passed; Notion auth URL + popup; GitHub connect idempotent; live What If 6/6 HTTP 200 (`live_verification.json`); double-sync dedupe 0 deltas.

**Not verified:** New raw ingest for commit `04d43e0` (already-ingested branch commits); full Goal Architect → forecast browser E2E with new evidence; live GPT A–G ablation on all frozen multi-domain labels.

## 2026-08-30 — Fresh GitHub evidence + simulate matrix + live A–G

**Hypothesis:** Recipe `resource_id` was rejected by Composio (`400 Extra inputs`), so branch commits never ingested; Evidence Agent HTTP API dropped `mcp_records`; What If Run must call `/simulate`.

**Changes:**
- Strip `resource_id`/`label` from Composio tool arguments; fail sync on tool `status_code >= 400`.
- Forward `mcp_records` on `POST /api/v1/agent/threads`.
- `useWhatIfSimulation.runScenario` → parse then `/simulate` (+ fast-reprice preview).
- Markets empty state `No goals yet`; What If dark tokens bind to `--app-*`.
- Artifacts: `github_fresh_e2e.json`, `github_evidence_forecast.json`, `whatif_simulate_matrix.json`, `live_ablation_ag.json`.

**Measured:**
- Fresh SHA `289316f…`: raw +1; evidence +1; history +1; published probability `0.3274` (`published_forecast`).
- Second sync: 0 new raw/events.
- What If `/simulate`: running `0.995→1.0`; finance `0.0068→0.011`; career LinkedIn/mock/apps/networking `NOT_PRICED` changes with near-zero uplift (honest).
- Live ablation summary: raw GPT probability-claim rate `1.0`; structured schema `1.0`; evidence hallucination `0.0`; intervention unsupported-claim rate `1.0`; critic leakage veto `true`.
- OULAD shared-200 unchanged: numerical `0.158` vs GPT `0.223`.

**Playwright:** foundation fixed; pass6_browser 4/4; plugins 3/3.

## 2026-08-30 — Hackathon proof v1 (pricing + agents + honest inventory)

**Hypothesis:** Aggregate measured proof can show education pricing superiority vs GPT and multi-domain agent honesty without fabricating non-education outcome labels.

**Changes:**
- `scripts/eval_hackathon_proof.py` — shared-200 A/C/G metrics, longitudinal, decay, MC/CRN, model-consistent policy regret, comparable agent arms, Source Planner NDCG@5, critic suite.
- `benchmarks/hackathon_proof_v1/` — `results.json`, `PROOF_TABLE.md`, `domain_inventory.json`.
- Expanded frozen `pass6_eval_v1/cases.json` (8 GA, 14 interventions, 6 SP domains, 7 evidence, 4 critic).
- Deterministic critic rejects `LLM_GENERATED_COEFFICIENT` provenance.
- Evidence prompt: dual-unit single observation rule; duplicate expect_events aligned with “no premature merge” contract.

**Measured (seed 20260830):**
- Education shared-200: Brier GPT `0.222799` → Play It Out `0.157994` (−29.1%; paired bootstrap P(Δ>0)=1.000).
- Longitudinal: Play It Out −27.2% Brier day14→105 vs GPT −16.8%.
- Source Planner mean NDCG@5 `0.987`; precision `0.892`; irrelevant rejection `100%`.
- Intervention: raw invents uplift `100%` on forced prompts; agent unsupported/NOT_PRICED `86%`.
- Critic suite accuracy `100%`.
- Macro multi-domain pricing: **not claimed** (inventory documents missing labels).

**Not verified:** cold browser Goal Architect→Paths for all families; causal ATE panels; GPT Source Planner NDCG head-to-head.

---

## 2026-08-30 — User-behavior follow-through + resource-specific Evidence

**Hypothesis:** A hierarchical Beta-Bernoulli on observed commitment trials can separate P(execute) from P(goal | fully executed), improve realistic What If pricing versus assuming 100% adherence, and Source Planner can rank exact MCP resources from metadata without hardcoded provider→goal maps.

**Change:**
- `behavior_hierarchical_beta_v1`: recency-weighted Beta-Bernoulli, global → domain → action shrinkage, session collapse.
- Display-only Execution profile radar (8 axes + provenance). Polygon area unused.
- What If returns current / full-execution / follow-through / execution-adjusted. Optimizer uses execution-adjusted value.
- Source Planner + SyncRecipe accept exact resources (Notion page/DB, GitHub repo + activity types, Sheets/Calendar/Drive/Gmail schema fields).
- Frozen protocol `behavior_adherence_v1`. Logistic refinement evaluated and **rejected**.

**Evaluation protocol:** `npm run evaluate:behavior`; held-out future commitments (n=109) after per-user history; baselines A 100% / B global prior / C recent-rate heuristic / D hierarchical model + ablations.

**Primary metric before:** What If treated a default 0.72 execution assumption or implicit full follow-through.

**Primary metric after (production model = action-shrunk Beta, no logistic):**
- Brier `0.235` vs always-100% `0.459` (−48.8% probability error)
- Brier `0.235` vs recent-rate heuristic `0.291` (−19.3%)
- Brier vs global prior: −0.1% (near-tie)
- When predicted ~70%, actual follow-through **78%** (n=36)
- Logistic ablation Brier `0.297` — not shipped
- Temporal decay (H=42 val-selected) did not beat no-decay action shrinkage on this split

**Decision:** Keep hierarchical Beta + action shrinkage. Do not ship logistic. Radar remains explanation-only.

**Why:** Assuming 100% follow-through is badly miscalibrated; the hierarchical mean is honest and context-sensitive. Domain/decay/logistic layers did not earn their complexity on this frozen set.

**Limitations:** Dataset is synthetic longitudinal, not live user commitments. Resource-ranking E2E uses mocked planner payloads for browser proof of UI order/selection.

**Artifact/run IDs:** `benchmarks/behavior_adherence_v1/results.json`; estimator `behavior_hierarchical_beta_v1`.


## 2026-10-17 - Phase 2 BYOK, inference routing and four-agent workflows

**Hypothesis:** explicit payer/provider routing, encrypted owner credentials, typed agent outputs and per-attempt budgets improve functional reliability without replacing the numerical forecasting kernel or redesigning the UI.

**Implementation:** native OpenAI Responses/Anthropic Messages/Spur adapters; owner-bound AES-GCM key storage and Settings lifecycle; deterministic validation; conditional bounded Monid research; append-only artifacts/lineage; explicit observation aggregation; atomic rate and daily reservations. Existing optional What If import was removed from core forecasting. No production deployment.

**Baseline:** 266 backend passed/2 skipped; 22 web tests passed; mypy 201 errors in 61 files. No empirical forecasting-calibration improvement claimed.

**Experiment P2-1 - native mocked A/B/C:** three protocol-adapter calls per workflow produce validated published numerical forecasts; snapshot 18 plus increment 5 -> 23. Hosted token debit 90; OpenAI/Anthropic BYOK hosted debit 0. Mocked tests establish contracts/accounting, not live provider acceptance.

**Experiment P2-2 - real Spur output budget (failed/removed attempts):** 2048 output tokens truncated the Architect schema; 4096 with upstream default reasoning timed out or truncated Intervention output. Preserved artifacts: `spur-workflow-initial-failure.json`, `spur-workflow-2048-token-failure.json`, `spur-workflow-4096-timeout.json`, `spur-workflow-4096-reasoning-failure.json`. No fabricated repair or cross-provider fallback. Explicit low reasoning effort plus 4096 floor succeeded; per-attempt reservations include the floor. Actual Spur invoice pricing is unverified.

**Experiment P2-3 - live hosted semantics/persistence:** actual Architect/Evidence/Intervention; aggregate applications 23; two published receipts reload with probabilities 0.1867957952249093 and 0.19440322757640105. Source `artifacts/phase2/spur-workflow.json`. This historical run recorded zero counterfactual uplift, exposing a wiring/math defect; it is retained unchanged.

**Experiment P2-4 - deterministic counterfactual repair:** effective hiring assumptions were not repriced, alias edits could be applied twice, and deadline Monte Carlo used independent worlds/incorrect boolean uplift and unconditional convergence. Reprice explicit edits once; use common worlds and execution mixture; honor error tolerance/draw caps. Version new receipts with engine 1.1.0. Separate replay `spur-counterfactual-corrected.json` uses the saved real parsed action with zero new LLM calls. Baseline 0.19440322757640105 -> conditional 0.47717884436641567 -> execution-adjusted 0.39800167166521155 at explicit 0.72 execution; +20.35984440888105 percentage points. Published history unchanged. This is an exploratory model result, not measured causal lift or calibration.

**Experiment P2-5 - live Monid/research:** discover/inspect/run HTTP 200, run 01M569Q3WY1R0P4VX3M05ZCMCB, quote $0. Initial document-only parser missed actual snippet fields; corrected parser preserves snippet/candidate identity. Retained GET returned irrelevant material. Actual Spur Research produced no claims and identified topic/population mismatch; validation returned insufficient_evidence and persisted/reloaded it. No numeric prior activation. Live synthesis estimate $0.012075. Artifact `research-live.json`.

**Experiment P2-6 - browser visual verification:** initial buttons had blank/poor contrast due incorrect token names; repaired to existing active app tokens. Six desktop/mobile Settings/foundation tests pass; screenshots re-rendered, new controls exercised, no console errors/overflow/saved browser keys. Routes mocked. Initial foundation failure was an auth test-server mismatch, repaired in harness without changing auth/design.

**Final regression:** 319 backend passed, 2 skipped (33.13s) including isolated Postgres; 22 web passed; web build/type/lint pass; architecture/migration checks pass. Targeted new Python lint passes; full mypy still 190 errors in 58 files, full Ruff 620 diagnostics before final formatting. No blanket green quality-gate claim. Live OpenAI/Anthropic and manual live Clerk acceptance NOT VERIFIED.

**Performance:** local in-memory Settings API p50/p95 4.00/5.44 ms (30); real PG settings service 4 queries. Deadline 2k/10k/20k draw p50 0.19/1.19/1.79 ms; p95 1.45/1.91/2.21 ms. Persisted corrected replay ~131 ms. No production load claim.

**Data preservation:** additive local migrations preserved user/goal/evidence/simulation/ledger counts. Test writes stayed in isolated Phase 2 DB. Docs/report/operations and artifacts are local because existing Git ignore excludes them. See `docs/PHASE2_ENGINEERING_REPORT.md` for files/contracts/security findings/remaining Phase 3 prerequisites.

P2 verification addendum: four existing resource/What If desktop browser tests also passed (10 browser cases total). Deadline fan endpoints now share execution outcomes; nonexecuted paths stay at baseline. Exact float-equality assertions initially failed for downward scenarios due representation error; changed to a numerical tolerance while retaining exact nonexecution/common-world assertions.

Final rerun P2-7: after fan-path endpoint assertions, 319 passed/2 skipped in 37.31s. Legacy opt-in live provider cases remain skipped; separate Spur proofs above remain the live evidence. Full mypy 190 errors/58 files; targeted new-file lint passes. No historical run results were replaced.

## 2026-10-17 — Phase 2 live BYOK acceptance (P2-8)

**Hypothesis:** the native OpenAI Responses and Anthropic Messages adapters work with actual owner-saved keys and report usable structured/text/tool outputs and ledger usage under a bounded budget.

**Run and evidence:** isolated `playitout_phase2_test` principals, Settings API save/validate/replace/select/delete, encrypted Postgres credential store, shared router, native HTTP adapters. OpenAI `gpt-5.4-mini`: five HTTP 200 POSTs in the retained run, 1,381 input/611 output tokens, estimated $0.00378525. Anthropic `claude-sonnet-5-5`: five HTTP 200 POSTs, 4,734 input/982 output tokens, estimated $0.019288. Both validated strict JSON and one tool call. Two typed agents per provider passed schema/domain probes. No hosted token debit, provider substitution or post-deletion HTTP was observed. Sanitized evidence: `artifacts/phase2/byok-live-acceptance.json` and engineering report addendum.

**Failed/removed approach:** the first harness run completed five live calls per provider but failed during its final cleanup assertion due to an async-generator expression. All credential rows were removed; its immutable ledger rows remain. Harness expression repaired and run repeated once. Combined across both runs, ledger-estimated provider cost was OpenAI $0.007809 and Anthropic $0.038406. This was a test harness defect; no production application defect or production code repair was needed.

**Boundary and decision:** native BYOK provider and Settings/ledger controls **LIVE PASS** for these models. Full BYOK graph/DB commit and numerical repricing of the newly generated proposal, real Clerk browser ownership, and induced real upstream errors **NOT VERIFIED**. Mock and earlier Spur evidence cannot substitute for these live proofs. Full backend regression passed with three skips; targeted Phase 2 backend tests, 22 frontend unit tests, targeted harness Ruff and `git diff --check` passed. No calibration or measured forecasting improvement claimed. No deployment. Temporary test keys were removed from isolated credential rows and local `.env` after the run.

## 2026-10-18 — Phase 2 Settings incident and full BYOK workflow (P2-9)

The Settings 404 came from an API process started before Phase 2 router registration. The direct frontend endpoint on port 8000 was correct; Vite had no proxy. Restarting the same API exposed the route: unauthenticated GET now returns 401 and a signed-in Clerk Settings page loads. Mocked Settings browser tests had separately reused the Clerk-enabled 5173 server. Playwright now owns a dedicated 5174 test server with auth bypass confined to that process; desktop/mobile Settings tests pass 4/4.

The full BYOK workflow ran isolated Settings save/select, native OpenAI or Anthropic inference, Goal Architect, two evidence updates, conditional Research, published deterministic forecasts, Intervention pricing, persisted What If, receipt immutability and ledger checks. Its first run issued successful provider requests but failed at a harness assertion (`PublishedBaseline.model_dump` on a dataclass). That failed run also exposed a real evidence-ordering defect: an Anthropic date-only increment described as “today” sorted before a same-day snapshot and was dropped. The normalization boundary now anchors that narrow relative-date increment to receipt time; regression covers same-day, precise and historical observations.

The rerun passed for both providers. OpenAI made 4/4 HTTP 200 Responses POSTs, 7,102 input/1,302 output tokens, estimated $0.0111855. Anthropic made 5/5 HTTP 200 Messages POSTs, 19,435 input/3,154 output tokens, estimated $0.07041. Both ended at 23 applications, published two receipts, priced and persisted a numerical What If with about +20.36 percentage points modeled execution-adjusted uplift at 0.72 execution, retained history, and used zero hosted tokens. Including the failed harness run, new-run ledger estimates were $0.0228925 OpenAI and $0.119822 Anthropic, below $0.25/provider. Sanitized artifact: `artifacts/phase2/byok-graph-live.json`. Isolated test credentials were deleted; local `.env` keys were preserved. No deployment or development-data write.

One genuine Clerk account loaded Settings and showed provider/model controls. Real second-user Clerk isolation, browser credential mutation on the user's account, and induced live upstream failure responses remain unverified. A development console AbortError during React cleanup did not prevent Settings loading. Numerical uplift is a model estimate, not observed causal improvement.

## 2026-10-18 — Phase 2 final acceptance hardening (P2-10)

The user added and replaced a real Anthropic BYOK key in the existing signed-in Clerk Settings browser; no key value was captured in tools or artifacts. Validation returned success. The agent saved Hosted → BYOK, confirmed persistence after reload, then, with the user's deletion confirmation, deleted the credential. BYOK remained selected without a key. Hosted was saved and a further reload confirmed Hosted and no credential. No paid generation was used; live allowance and BYOK usage were zero throughout, so nonzero live quota accounting remains unverified. A second signed-in Clerk identity was unavailable; live cross-user isolation remains unverified despite isolated owner-scope tests.

Ten controlled native-adapter/router cases injected 401 invalid key, 429, timeout, malformed structured output and 503 unavailability in hosted and BYOK modes. Each produced one selected-provider attempt, explicit error, no key leakage, no stranded reservation, and no hosted debit under BYOK. Cancellation settled a hosted reservation conservatively in both memory and the isolated Phase 2 Postgres database. The older Phase 0 test database lacked a Phase 2 ledger column; the new Postgres test gates on that migration and the successful run used `playitout_phase2_test`. No provider calls were purchased for these tests.

The Settings AbortError came from React StrictMode aborting an initial read-only GET on effect cleanup. The component now ignores a late response after unmount; a fresh Clerk browser tab showed zero AbortError entries. Four AuthGate lint errors were fixed without changing auth behavior. Full backend regression, 22 web unit tests, build, lint (zero errors) and four desktop/mobile Settings browser tests passed. No Phase 3 work or deployment.

## 2026-10-18 — Phase 4 remote MCP server for personal agents (P4-1 to P4-6)

**Hypothesis:** an authenticated remote MCP endpoint that is a thin adapter over the existing goal, evidence, forecast and What If services lets an external agent read and update a user's markets with the same numbers as REST, without an LLM ever producing a probability and without spending credits on structured or read paths.

**Implementation:** `/mcp` inside the existing FastAPI app using the official MCP Python SDK 2.3.0, Streamable HTTP in stateless JSON mode. PlayItOut is its own OAuth 2.1 authorization server: protected-resource metadata, authorization-server metadata, dynamic client registration, PKCE S256, RFC 8707 resource binding, Clerk-gated consent page, per-connection scopes, opaque hashed rotating tokens and revocation. Ten tools; additive migration `0015_mcp_oauth.sql` (`remote_mcp_*` tables); Settings → Personal agents and `/connect/authorize`. No production deployment, tunnel or paid infrastructure.

**P4-1 — What If override defect (behavior change, found by MCP/REST parity tests):** for composed growth goals, explicit What If edits to `mu`/`primary.mu` were applied before the growth rate was estimated from history, so the estimate silently overwrote them while the receipt still reported `parameter_intervention`. This affected REST and MCP equally. `composition.py` now reapplies explicit overrides after estimation and matches node-qualified keys only for parameters that exist. Regression: `test_composition_overrides.py` (3). On the E2E audience goal, `primary.mu = 0.2` now moves the scenario by +98.18 percentage points from a 1.82% baseline; before the fix it moved 0. Earlier What If receipts are not rewritten.

**P4-2 — contract additions:** Evidence `source_type` gains `personal_agent` (MCP-submitted evidence is always `agent_reported`; the client cannot raise trust). Unmapped What If changes return `NOT_PRICED`/`unmapped_intervention` on both surfaces instead of a silent zero delta.

**Failed/removed approaches:** (a) the SDK `/revoke` handler requires `client_secret`, so public PKCE clients got 400; replaced with a route that reuses the SDK client authenticator with the secret optional. (b) DCR default scopes initially excluded `inference:use`, making step-up impossible; registration now allows all scopes and user consent remains the gate. (c) the first migration collided with an unused 0006 `mcp_connections` table (`column "user_id" does not exist`); it rolled back cleanly and all tables were renamed `remote_mcp_*`. (d) the NOT_PUBLISHED message used the What If priceability check, which mislabels binary goals; replaced with requirements-based missing-input text. (e) one E2E run reported `revoked_token_rejected` FAIL because the script revoked an older same-named connection; the script now matches its own `client_id`, and the rerun passed. Two leftover isolated-DB connections were revoked.

**Pre-existing UI defects repaired during browser verification:** `auth.css` referenced palette variables from the no-longer-imported `styles.css`, so every auth screen rendered unstyled; the palette is now scoped to `.auth-screen` for light/dark. The shared invite/endpoint copy button used undefined `--app-text` (transparent background); it now uses `--app-ink`.

**Verification:** backend 437 passed / 4 skipped, including 72 Phase 4 tests (16 protocol, 23 OAuth, 24 scenarios B–F/H, 6 real-Postgres atomicity, 3 composition). Web 24 unit tests, typecheck, lint (0 errors) and build pass. Architecture and migration checks pass. Ruff and strict mypy are clean on all Phase 4 files; repo-wide mypy still reports 251 errors in untouched files. Scenario G with the SDK `OAuthClientProvider` against a real local server and Postgres: 12/12 checks PASS. Browser: Settings and consent on desktop/mobile, light/dark, approve with a narrowed scope, deny, reuse rejected, revoke → 401; zero console errors; no tokens in DOM or storage. Server log contained no tokens, codes or bearer values.

**Performance (local, one process, Postgres, n=30):** p50/p95 ms — `list_goals` 72.3/76.0, `get_forecast` 81.4/89.4, `get_observation_policy` 61.3/68.8, `simulate_intervention` 62.1/71.3. Each includes token lookup, connection check and an audit write. No production load claim.

**Not verified:** Grok, ChatGPT, Claude or any hosted assistant (needs a public HTTPS deployment). Natural-language submissions were tested with scripted providers only; no paid model call was made. $2 per-user and $25 global hosted quotas are unchanged; no $100 cap was added.

## 2026-10-18 — Pre-staging hardening (security, What If presentation, migrations)

**Hypothesis:** private staging can be entered without raising the hosted cap or claiming a real Clerk/hosted-MCP pass, if test auth cannot start in a deployed process, `/health/details` cannot leak on a public host, and What If stops presenting degenerate intervals as measured CIs.

**Security:** `Settings.assert_safe_startup()` refuses `PM_DEV_BOOTSTRAP_TEST_USERS` and `PM_TEST_AUTH_SECRET` when the environment is not local or `PM_PUBLIC_API_URL` is public HTTPS. `/health/details` is loopback-only and ignores `X-Forwarded-For`. Forwarded-header trust defaults off; staging behind a proxy must set `PM_TRUST_FORWARDED_HEADERS` and `PM_TRUSTED_PROXIES`. MCP rate limits and goal locks remain process-local; startup logs `single_worker_required`. Uninvited Clerk-shaped JWTs get 403 on private APIs; wrong issuer/tampered JWT get 401.

**What If:** growth clip floor probabilities are not rescaled. Composed parameter edits are labelled `parameter_intervention` / hypothetical, including when one probability sits on the 1e-6 bound (~100 pp lift). Monte Carlo uplift intervals that have zero sampling width return `null` instead of `[0, 0]`. The UI shows `—` for a degenerate likely range and surfaces the model message.

**Migrations / budget:** 0001–0015 applied on a throwaway `playitout_hardening_fresh` database (then dropped). Isolated Phase 2 Postgres tests pass on a fully migrated DB and skip with an explicit 0001–0015 message otherwise. Hosted global cap remains $25; kill switch tests still pass. Architecture check forbids eval scripts from application routes. No $100 cap. No deployment.

**Verification:** backend 482 collected / 0 failed / 4 skipped (default unmigrated `playitout_phase0_test`); vitest 28; web typecheck clean; architecture and migration checks pass. Real Clerk Google workflow **NOT VERIFIED** (`access_denied` callback; 5173 showed Sign in). Hosted MCP clients remain deferred to staging acceptance.

**Decision:** READY FOR PRIVATE STAGING with the documented operator prerequisites. NOT READY FOR PUBLIC JUDGE ACCESS.

## 2026-10-19 — Pass 06 live production browser acceptance, navigation repair

**Experiment:** test the deployed Vercel + Render application in the existing Clerk Google administrator session. Starting commit `2963d37`. No benchmark scores are changed.

**Observed:** authenticated empty Markets had no goal-creation entry point. Loading `/new` redirected an uninvited administrator to Settings; the same condition would discard explicit goal/What If URLs on refresh. The restored composer also rendered with browser-default styling because its old global CSS is not imported. Goal workflow errors discarded the server's actionable explanation. Hosted provider reports `none`, no stored OpenAI BYOK key, zero hosted quota and usage. Clerk console warns about development keys.

**Changes:** visible Create goal link; administrator landing redirect applies only to `/` and `/invite`, preserving explicit product routes; scoped composer styling using existing tokens; show API workflow errors and recovery link to Settings. Public API and mathematical contracts unchanged. No provider credentials, quota, infrastructure or database changes.

**Verification:** 59 web unit tests; two local Playwright regression cases (desktop/mobile, fixture-backed and explicitly not live acceptance); production build/typecheck; ESLint zero errors / ten existing warnings; 61 backend auth/quota/inference-selection tests; architecture and migration checks. First unit parametrization failed due to array spreading and was corrected. First lint run found require-await in a new test stub, corrected. Bare `uv run pytest` selected an unsuitable entry point; `uv run python -m pytest` passed. Initial visual review caught unstyled composer; scoped CSS repair passed the repeated desktop/mobile browser path.

**Live status:** acceptance remains blocked on production inference configuration; root `PASS_06_LIVE_E2E_REPORT.md` records final evidence and deployment recheck. No paid inference initiated ($0.00). No claim of completed goal/forecast/What If/provider acceptance from mocked tests.

## 2026-10-19 — Pass 06 follow-up: invitation completion and honest Social state

**Observed live:** bounded test invitation POST returned 200 at 17:01:44 EDT, but Settings remained Generating because automatic `navigator.clipboard.writeText` was awaited before refreshing invitation history. Reload recovered the persisted row; Revoke succeeded, zero redemptions. No URL was distributed. Local mobile regression then found the active row could overflow and block the Revoke hit target.

**Changes:** generation completes independently of clipboard permissions; Copy remains an explicit action and clipboard rejection shows an error. Constrain the invitation URL flex child and stack row actions on narrow screens. Replace hardcoded Social names/+pts (observed live, violating no-demo-odds invariant) with an explicit unavailable/empty state.

**Verification:** regression intentionally leaves clipboard permission unresolved; creation, revoke and refresh pass in desktop and mobile Playwright (4/4 total scenarios including goal failure). Unit/type checks corrected two new fixture type errors and an ambiguous test selector. Build/typecheck and lint pass; final counts and deployed recheck in root acceptance report. No numerical-model changes or benchmark-result edits. No paid inference.

## 2026-10-19 — Pass 06 malformed Clerk JWT failure handling

**Live failure:** GET /api/v1/me with a synthetic, unsigned, expired admin-claim JWT returned 500 (Internal Server Error), without granting access. Normal absent/invalid bearer/header-spoof cases returned 401. Cause: JWKS key lookup errors (`PyJWKClientError`) were not mapped to UnauthorizedError; unsupported alg / missing kid reached lookup before decode rejected them.

**Repair:** reject unsupported RS256 signing headers/missing kid before external key lookup; map typed JWKS lookup errors to 401 invalid token. Signature, issuer, expiry, origin, invitation and role enforcement remain required. No provider or infrastructure settings changed.

**Verification:** 79 selected backend tests pass (Clerk signed RSA acceptance, issuer/azp/signature/expiry rejection, five added malformed/unknown-key cases, identity/quota/inference regressions); Ruff clean on affected Python files. Live deployment recheck recorded in root report. No model calls or benchmark changes.

**Pass 06 final deployment recheck:** Render 9a5eb1d Live; forged unsigned expired admin-claim request changed from500 to401 at17:11:48 EDT (old instance overlap17:11:29 still500 retained in report). Post-fix bounded invitation POST20017:10:02, revoke20017:11:15; both PASS06 invitations persist Revoked0/1 after reload. Deployed Social honest empty state. Separate signed-out browser gates access. Paid inference $0.00; core goal/forecast/What If chain remains BLOCKED by live provider/allowance configuration. No new benchmark score claimed.

## 2026-10-19 — Judge inference credits and one-step BYOK (JIC-1)

**Hypothesis:** Raising the existing cumulative hosted budgets to $5 per invited user and $100 global, and committing validated credential plus BYOK preference atomically, makes judge onboarding usable without a second settings save or a duplicate ledger.

**Changes:** `867412f` changed application and Render defaults, updated Settings credit display, and made encrypted key storage plus preference change one Postgres transaction. `f1f35f4` let an unentitled administrator redeem a private invitation through the ordinary path. `34697e8` exposed hosted provider readiness separately from credit balance. Prior $2 invitations were deliberately not rewritten. No forecasting probabilities, benchmarks, or historical measurements were changed.

**Measured result:** Targeted backend tests, 63 frontend unit tests, and eight fixture-backed desktop/mobile browser paths passed. In live Chrome, a private one-use admin invitation redeemed with HTTP 200, became 1 / 1 Filled, and granted $5.00 / $5.00 hosted credit; the state persisted after refresh. Global remaining displayed $100.00. Render hosted provider/model displayed OpenAI / `gpt-5.4-mini`. Live goal creation after entitlement returned HTTP 503, “Selected hosted provider is not configured”; credits stayed $5.00. No real hosted or BYOK provider call was possible because Render lacked `PM_OPENAI_API_KEY` and `PM_BYOK_ENCRYPTION_KEYS`; paid cost $0.00. See `JUDGE_INFERENCE_ACCEPTANCE.md`. These behavior tests do not claim a calibration or Brier Score improvement.

## 2026-10-19 — Production upgrade: Spur fail-closed, dashboard batch, collections

**Hypothesis:** Judge-ready product quality is blocked by hosted-provider mismatch, N+1 Markets reads, empty plugin pages, withheld-forecast UX, and missing collection/profile/deletion primitives — not by inventing published odds.

**Changes:** Fail-closed Spur hosted inference (no OpenAI/Anthropic hosted fallback); BYOK model discovery from provider `/models`; admin-only global remaining; `GET /api/v1/goals/dashboard`; React Query stale-while-revalidate; Composio catalog cache with Manual/CSV retained on provider error; Hosted vs BYOK settings split; GitHub-inspired create control; owner-scoped soft archive; collections with progress (not joint probability); private `/profile` radar; persisted `last_publication` withhold reasons. Additive migration `0016_collections_profiles.sql`. No benchmark scores edited. No production data rewrite. Paid inference $0.00.

**Measured result:** 12 production-upgrade API tests passed; auth/API/behavior and forecasting/settings suites passed; web App tests 6/6; web typecheck passed. Live Render `/health` still returned a cold-start interstitial, so this SHA is not a live judge proof. Supabase migration list timed out; 0016 is not confirmed applied. See `PLAYITOUT_PRODUCTION_UPGRADE_REPORT.md`.

## 2026-10-19 — Signed-in production remediation follow-up

**Measured live failures:** A reading-goal What If manual-state retry ended in browser `TypeError: Failed to fetch`; no numerical result was claimed. Profile save consistently returned the same error. The latter traced to CORS preflight rejecting PATCH, while browser GET and collection POST worked. At 390 px width, the Markets collection progress label overlapped the title. The existing Evidence page exposed 49 unrelated sources and raw GitHub tool names; Settings placed model choices in a narrow black stack. No new forecasting accuracy score is claimed.

**Changes under test:** Add PATCH to the API CORS allowlist with a preflight regression; consume entered manual count/rate evidence and support declared parameter overrides in composed forecasting; persist composed What If scenarios; avoid paid natural-language parsing on each keystroke; queue scenario retry after baseline inputs; preserve pending Composio auth; fail closed on unsupported GitHub source activities; simplify Evidence upload/source configuration and Settings picker CSS; repair mobile collection layout and empty-state copy. Existing historical evidence and forecast snapshots remain unchanged.

**Verification at commit time:** 39 selected backend tests and web production build passed. The authenticated browser created a collection in the hosted DB, reloaded it, assigned a goal, and saw 0/1 members. Profile GET showed one goal and one collection. The browser also reproduced Profile PATCH failure before the CORS repair was deployed. No additional paid inference was intentionally run; BYOK usage was already 108 calls / 529,968 tokens / estimated $1.9796 before a reliable pass baseline could be established. Live post-deploy results belong in `PLAYITOUT_PRODUCTION_UPGRADE_REPORT.md`.
