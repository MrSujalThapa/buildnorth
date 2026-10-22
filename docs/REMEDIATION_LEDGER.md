# PlayItOut remediation ledger

Source of truth for the 2026-10-22 complete-product pass. Do not treat a passing test count as completion.

Branch: `ux/consumer-profile-whatif`  
PR: https://github.com/MrSujalThapa/buildnorth/pull/1  
Production: `main` `d3073d8` — do not merge until preview acceptance is real.  
Cron / watch-runner / Render billing: **do not touch**.

Do **not** write synthetic evidence into the signed-in production account.

---

## Status key

PASS / PARTIAL / FAIL / BLOCKED / NOT TESTED

---

## Root-cause map (verified in current tree)

| Area | Root cause | Layer |
|---|---|---|
| Reverse | `buildTargetSearchRequest` sends `candidates: []`. Optimizer enumerates that empty list. | Frontend adapter |
| Compare | Paths come only from `baseline.compare_candidates`. Custom text adds the next catalog chip. `_simulate` gets `effect_per_unit=None` and no `parsed_changes` → NOT_PRICED. | Frontend + `compare_paths` |
| Compare zeros | `priced.scenario_probability or 0` (and quantile `or 0`) turns unpriced into 0%. | `what_if/service.py` |
| Futures | `parse-decision` is regex taxonomy. Request has labels, no `parsed_changes`. Continuous MC uses `intervention_effect=0` and **baseline** terminal outcomes. Decision changes labels, not the distribution. | `futures_weights.py` + request builder |
| Change | Composer `parsed_changes` work after `parse-intervention`. Auto-reprice `action` is stuck at 0, so `effect_per_unit` is unused. | `useWhatIfSimulation.ts` |
| Simple vs Deeper | Same simulation result; CSS layout only. | Frontend |
| Radar | Profile radar is still the rejected six execution traits (`portfolio.py` filter). Live production profile is empty because `n_eff < 4`. Previous “colorful radar” used mocked Playwright values. Product needs configurable parameters + isolated demo fixtures, not a recolor. | Domain + fixtures |
| Demo fixtures | `PM_DEV_DEMO_FIXTURES` is What If only, off in `.env`, blocked in production. `seeds/demo.json` has no commitment/radar/parameter histories. | Seeding |
| Preview | Unique Vercel preview can auth after CORS allowlist on Render. Git-alias still 403 from Vercel Deployment Protection. Preview talks to production API — must not seed that user. | Deploy |
| Plugins | `browse=true` exists; popular list still local-first. Catalog completeness unverified live. | Integrations |
| Observability | Codex cron ownership unresolved. | Out of scope |

`fix/consumer-catalog-and-profile-taxonomy` is unverified. Review, do not merge blindly. It still keeps the six-trait radar.

---

## Deliverables

| ID | Deliverable | Status | Notes |
|---|---|---|---|
| W1 | Shared intervention/baseline/parsed_changes used across four modes | PARTIAL | Contracts wired; live preview against production API still lacks new fields |
| W2 | Change: NL → parsed_changes → numerical delta | PARTIAL | Submit path exists; auto-reprice still unused for `action` |
| W3 | Futures: decision conditions MC/funnel, not labels only | PARTIAL | Goal-family labels; startup/hiring/finance parsed_changes shift mass in unit tests. Live preview not accepted |
| W4 | Compare: two user-specified paths, no 0% for unpriced | PARTIAL | Path A/B composers + null unpriced |
| W5 | Reverse: non-empty candidates + ranked feasible paths | PARTIAL | Assumption-lever generation + binary search + re-simulation. Live Reverse not accepted |
| W6 | Simple vs Deeper: different computation | PARTIAL | Draws 2000 vs 8000; sensitivity only in Deeper; opportunity costs in deep UI |
| G1 | Goal create / forecast-readiness distinction | NOT TESTED | |
| R1 | Parameter radar (not six traits) | PARTIAL | Selectable presets persisted as `__param__:` markers; live chart not accepted |
| R2 | Isolated demo parameter/fixture dataset | PARTIAL | `GET /api/v1/profile/demo-radar` unchanged; does not write user rows |
| P1 | Profile editor polish + photo persist | PARTIAL | Save waits for photo upload/removal; failures keep the editor open. Browser not accepted |
| L1 | Plugin full catalog + icons | PARTIAL | Auto-paginates `browse=true` after popular list. Live catalog not counted |
| N1 | Notion resource identity trace | PARTIAL | Gateway title/URL work; live account not re-traced |
| M1 | Isolated demo markets/collections/histories | PARTIAL | `GET /api/v1/profile/demo-portfolio` + Markets `?demo=1`. Nonlinear synthetic_demo histories; no user writes |
| O1 | Observability scheduled loop | BLOCKED | Cron owned by Codex |
| X1 | Consumer UX, composer attachments, speech | PARTIAL | Mic uses browser Speech Recognition; attach control is disabled with an honest reason |
| K1 | Performance measurements | PARTIAL | Local `/health` 70ms after Postgres was up. No signed-in p95 on What If/simulate |
| D1 | Preview + authenticated browser matrix | PARTIAL | Git-alias still SSO-protected; production Render lacks new contracts |

---

## Checkpoints

### 2026-10-22 — What If contracts + parameter radar

- Reverse sends compare-candidate interventions; backend fills empty candidate lists from baseline.
- Compare unpriced stays `null`, not `0`. Custom Path A/B parse to `parsed_changes`.
- Futures MC uses the scenario arm when parsed changes exist.
- Unsupported Futures is `priced: false`.
- Simple vs Deeper use 2000 vs 8000 Monte Carlo draws.
- Profile radar scores measurable parameters; isolated demo radar does not write the signed-in user.

Tests: `test_what_if_contracts.py`, futures, pass4 remaining, parameter profile, vitest adapters/radar.

---

### 2026-10-22 — Goal-family Futures, Reverse levers, Deeper sensitivity, demo markets

- `parse-decision` loads the goal and uses family outcome labels. Regex no longer gates pricing.
- Startup Futures apply `parsed_changes` onto `StartupState` before `derive_outcome_weights`. Hiring/finance already shifted; tests assert raise-seed and offer mass move.
- Reverse generates flow / weekly_application_rate setpoints, re-simulates them, and always enables bounded binary search when those assumptions exist.
- Simple analysis skips sensitivity; Deeper requests it and shows opportunity costs / fragility.
- Profile Save waits for photo upload or removal and keeps the editor open on failure. Parameter axes are user-selected presets, not life areas.
- Isolated `GET /api/v1/profile/demo-portfolio` backs Markets `?demo=1` with `synthetic_demo` histories. Plugins auto-browse up to 8 catalog pages.

Tests: contracts, futures (startup+hiring conditioning), demo portfolio, parameter selection, vitest adapters/radar.

### Deployment blocker (do not treat as end of pass)

- Exact commit `32572be` unique preview: `https://buildnorth-eb8pzeuj8-sujalthapa242-3741s-projects.vercel.app`. Vercel Deployment Protection sends unauthenticated browsers to `vercel.com/login?next=/sso-api?...`. Do **not** disable SSO.
- The dashboard **Share** control on that deployment is team-member access ("Only people with access can view"), not a Deployment Protection Shareable Link / `_vercel_share` bypass. Protection Bypass for Automation was not created (requires Deployment Protection settings + Hobby one-link limit).
- Production CORS: git-alias origin OPTIONS `/api/v1/me` **200**. Unique `eb8pzeuj8` origin OPTIONS **400** (not on Render allowlist). Production origin 200.
- Production Render still serves `main` and lacks `include_sensitivity`, `demo-portfolio`, goal-family `parse-decision`. Compatible API for this commit is local `npm run dev:api` on `:8000` (OpenAPI contains `parse-decision`, `demo-portfolio`, `include_sensitivity`). Local `/health` 70ms. Local Vite `:5173` is signed **out** (Clerk Google). Unauthenticated `GET /api/v1/profile/demo-portfolio` is 401 as required.
- Local API cannot start without Docker/Postgres `127.0.0.1:54322`. Docker was down; after `supabase start`, the branch API booted. This is local, not production, and does not write `sujalthapa242`.
- Do not seed production `sujalthapa242`. Cron/watch-runner untouched.

---

## Next unfinished task

If interrupted: create a Vercel Deployment Protection **Shareable Link** (not team Share) for git-alias `buildnorth-git-ux-consumer-c0fb66-...` without disabling SSO; keep using local `:8000` as the compatible API until a non-production host exists. Then signed-in A–L. Cron still owned by Codex.

### 2026-10-22 — authenticated local goal creation failure

- Verified local browser at `localhost:5173`, branch API at `127.0.0.1:8000`, and isolated development PostgreSQL at `127.0.0.1:54322`. Genuine Clerk session was active. No hosted Supabase write occurred.
- Input: “Read 20 books by December 31, 2026. I have finished six books so far.” Browser stayed on “Understanding goal…” for two minutes, then showed a blank New market body. Local `workflow_threads` recorded `running / parse_request` for over four minutes, with no new `agent_runs` row. This is **FAIL** for G1; no goal or forecast was created.
- Fix in progress: New Goal now receives the async thread immediately, polls status, shows honest progress, and stores the thread ID in session storage to recover after reload. Polling no longer overwrites a terminal background failure with an older LangGraph running checkpoint. Three frontend and two backend focused tests pass; the full real goal journey remains failed until the backend call is traced and rerun.
- Render Cron form was opened but never submitted. The newer branch-specific instruction leaves cron ownership unresolved; no new paid service was provisioned.

### 2026-10-22 — local retry and isolated portfolio walkthrough

- The second authenticated local goal submission failed visibly instead of leaving a blank page. Local Settings showed zero hosted inference balance for this identity; no goal, receipt, or forecast was created. **G1 remains FAIL**. An older local `running` thread is now expired after the configured inference timeout plus 60 seconds, with a conditional database update so polling does not leave it indefinitely running.
- The first real-browser demo portfolio had a 0% collection card and a +4.2 pp claim despite member goals in the 22–57% range. Its synthetic series used fractions where the collection UI expected 0–100; the change was hardcoded. The fixture now supplies six isolated goals, four collection members, 0–100 series, and a portfolio value/change calculated by the production portfolio helper. No account rows are written.
- Authenticated desktop browser verification at `localhost:5173` opened a synthetic collection, visually inspected its four-line chart, returned to demo Markets, and opened a synthetic reading goal. Demo goal/detail actions do not touch real evidence or What If. The collection detail required its route CSS plus spacing/typography repair. Synthetic odds are now labeled illustrative. **M1 remains PARTIAL** until mobile and broader interaction acceptance.
- Focused API tests: 3 passed. Web production build/typecheck passed. Real local browser paths were verified at desktop width; mobile authenticated verification and production preview remain outstanding. No Render cron was provisioned, and no paid inference was used in this pass.

### 2026-10-22 — authenticated Profile visual and save pass

- Real local Clerk session showed a sparse authentic Profile and the isolated parameter demo. Screenshot review exposed a circular grid, tiny disconnected spokes for five measured axes and one unknown axis, duplicate demo copy, and a tooltip covering the chart. The grid is now polygonal, adjacent measured values form an open line, unknown axes remain unfilled, and the detail card sits below the chart. The page now has a clear Profile heading.
- In the local isolated database, editing display name and bio saved, survived a full browser reload, and was then restored to the original empty fields. No production profile was changed. Photo upload/removal, parameter preference persistence and mobile acceptance remain **NOT TESTED** in this pass.
- Radar component tests: 3 passed, including the open-line sparse case; frontend typecheck passed. Visual inspection was desktop Chrome at `localhost:5173`.
- A later Plugins navigation showed the shell's account label still using the temporary profile name after the Profile page had restored the original fields. AuthGate held the account from its first `/me` call while Profile invalidated only its own query. A narrow account-refresh context now updates the shell after successful profile saves; local profile save/restore was rerun. The local Plugins page displayed 11 fallback entries and an explicit unavailable-catalog notice because this local stack has no Composio catalog connection. Full provider catalog, OAuth and Notion resource checks remain **NOT TESTED** here.
- Local authenticated route timing from the structured API log (mixed first/warm requests, small samples): goals dashboard n=5 p50 316 ms / p95 1073 ms; Plugins n=8 p50 171 ms / p95 1547 ms; Profile n=12 p50 247 ms / p95 1270 ms; photo endpoint n=6 p50 229 ms / p95 1399 ms. These are local API durations, not browser navigation or deployed before/after evidence. The local account has no goals and no Composio catalog, so the slow production paths remain open.
- The parameter editor initially showed all six checkboxes unchecked even though an empty saved preference means all presets, and allowed saving fewer than three axes into a radar that only renders with three. It now initializes all six for an empty preference and requires three. A real local save of three axes survived browser reload; the all-axes configuration was restored afterward. Local photo upload via Chrome was attempted with the repository test avatar, but the ChatGPT Chrome extension denied file chooser access until its “Allow access to file URLs” setting is enabled. No photo was selected or uploaded, and the edit dialog was cancelled. Photo E2E is **BLOCKED** by that browser permission in this session.
- Profile Save previously patched name/bio before photo upload, so a failed upload followed by Cancel could leave text changes in storage. The save flow now attempts a compensating text restore on photo failure and explicitly reports if that restore also fails. Three focused transaction-order tests pass. True atomic text/photo persistence would require one backend transaction across both resources; photo browser E2E remains blocked.
- Stale goal workflows now retain a safe `workflow_timeout` code in their stored debug object (without overwriting other debug fields). New Goal shows a specific timeout message after reload instead of a generic provider failure. Four focused frontend goal tests and Ruff pass. This improves recovery feedback; the local zero-entitlement account still cannot complete a new goal.

### 2026-10-22 — demo removal, behavior traits, owner-scoped workspace seed

- **Demo product removed.** `profile/demo_portfolio.py`, `demo_fixtures.py`, `?demo=1`, the What If demo preview fallback and `DEMO_SEED` paths are deleted. The `synthetic_demo` history filter stays as a defensive guard. `scripts/seed_demo.py` (CI database fixture idempotency gate) is unchanged.
- **Behavior traits.** `behavior/traits.py` estimates Discipline, Goal realism, Focus, Time management, Consistency and Recovery (plus user-defined custom traits) from commitment trials and evidence, with intervals, observation counts, per-context series (career / personal / relationships) and sources. Custom traits score only from evidence recorded as `trait_<slug>` on a 0–1 scale and stay empty otherwise. Only Discipline feeds forecasts (What If execution probability); the others are exploratory. Migration `0022_profile_parameters.sql` adds `app_users.profile_parameters_json` and `workspace_seed_records` (additive, nullable).
- **Profile radar.** One chart, shared axes from the saved selection, one polygon per context, legend, readout. Single "Edit parameters" editor: add, remove, reorder, custom (name + meaning), save, cancel. Local authenticated-bypass browser pass: added Recovery, moved Focus above Goal realism, added custom "Sleep regularity", saved, reloaded — order and custom axis persisted; the custom axis renders dashed with "—". 390 px viewport has no horizontal overflow. Window label rounding bug ("92.0001849 days") fixed.
- **Workspace seed** (`POST/GET/DELETE /api/v1/admin/workspace-seed`, admin-only, seeds the caller's own account). Seven goals and two collections go through the Goal Architect refinement/contract compiler, evidence commit and the real pricing service; each evidence batch is published with its historical timestamp, so histories are model outputs, not drawn curves. Evidence is `source_type=manual` with `seed:` identities and goals carry `model_requirements.workspace_seed`; nothing is labelled as Notion/GitHub/provider data. Registry is append-only; removal archives seeded goals and deletes seeded collections only. Retry after a partial failure retires the broken goal and creates a new generation.
- **Model defects found by the seed** (see changelog): startup hazard applied weekly instead of monthly (99% from day one); running trend extrapolation flipped 0%↔100% with no slope uncertainty; project goal phrased as milestones routed to the unpriced DAG family.
- A trailing "publish at now" step was tried and removed: publication dedupes on evidence watermark, so time passage alone never creates a revision. Market cards now show the last revision change and age ("+17.3 pp · 4d ago") when nothing changed today; collection cards caption "Average of N of M priced markets".
- Local verification: full backend suite passed, 92 web tests, lint/typecheck baselines (no new findings), architecture, migrations, build. Local seed ~11 s; profile ~290 ms; dashboard ~90 ms.

### 2026-10-22 — production deploy `a967e47` and authenticated acceptance

- PR #1 merged; Render `/health` reports `a967e47ff13c`; the Vercel production bundle contains the new strings. Rollback point `d3073d8`.
- Signed-in production session (Playwright extension, real Clerk Google session for `sujalthapa242`). Existing real goals ("Complete 12 guitar practice sessions", "Read 20 books by end of 2026") and the existing "Personal" collection were left untouched. Seeded via `POST /api/v1/admin/workspace-seed`: 7 goals + 2 collections in ~3 min (about 15–20 s per goal against hosted Postgres vs ~1.5 s locally; sequential publication round-trips).
- Markets, collection detail, goal detail and Profile radar render the seeded histories with the same values as local. Discipline (81%) appears as What If "Estimated follow-through".
- **Latency defect found:** warm `/health` 110 ms but `/api/v1/me` 2.4–3.0 s, `/api/v1/goals` ~1.27 s, `/api/v1/profile` 4.0–4.9 s. Each authenticated request constructed a new `PyJWKClient`, fetching Clerk JWKS synchronously and blocking the event loop. Fixed by caching the client per JWKS URL (PR #2); after-deploy timings to be appended.
- **What If Change failure found:** "What if I study LeetCode 2 hours a day?" returned 422 after ~30 s — the user's BYOK Claude Sonnet 5.5 hit the 1200-token default output limit on the intervention schema. The page showed no error and no busy state. Fixed: named `intervention_max_output_tokens = 4096` for the intervention agent (BYOK application limits still enforced), busy state covers parse/persist, and failures render an alert.
- Remaining console noise: `/api/v1/profile/photo` 404 when no photo exists; Clerk development keys warning in production (switching to a production Clerk instance is an account-level change not made here).
