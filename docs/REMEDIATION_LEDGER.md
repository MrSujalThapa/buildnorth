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
| K1 | Performance measurements | NOT TESTED | |
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

- Vercel git-alias remains behind Deployment Protection SSO. Shareable Links / Protection Bypass for Automation were not created from this session (Hobby one-link limit; requires dashboard/token).
- Production Render `playitout-api` is still `main` and ignores new request fields. Compatible backend for this commit is the branch API, not production.
- Do not disable SSO. Do not seed `sujalthapa242`. Cron/watch-runner untouched.

---

## Next unfinished task

If interrupted: push this branch, obtain a Vercel Shareable Link or bypass token without disabling SSO, run the branch API (not production Render), then signed-in A–L acceptance. Cron still owned by Codex.
