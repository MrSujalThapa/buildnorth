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
| W1 | Shared intervention/baseline/parsed_changes used across four modes | PARTIAL | Contracts wired; live preview against production API not yet |
| W2 | Change: NL → parsed_changes → numerical delta | PARTIAL | Submit path exists; auto-reprice dead |
| W3 | Futures: decision conditions MC/funnel, not labels only | PARTIAL | Unit test: higher contribution raises target mass |
| W4 | Compare: two user-specified paths, no 0% for unpriced | PARTIAL | Path A/B composers + null unpriced |
| W5 | Reverse: non-empty candidates + ranked feasible paths | PARTIAL | Adapter + `_ensure_search_levers` |
| W6 | Simple vs Deeper: different computation | PARTIAL | Draw counts differ; deeper sensitivity not yet |
| G1 | Goal create / forecast-readiness distinction | NOT TESTED | |
| R1 | Parameter radar (not six traits) | PARTIAL | Parameter estimator + UI reject six-trait skeleton |
| R2 | Isolated demo parameter/fixture dataset | PARTIAL | `GET /api/v1/profile/demo-radar`; does not write user rows |
| P1 | Profile editor polish + photo persist | PARTIAL | Photo flow exists; area modal crude |
| L1 | Plugin full catalog + icons | PARTIAL | |
| N1 | Notion resource identity trace | PARTIAL | Gateway title/URL work; live account not re-traced |
| M1 | Isolated demo markets/collections/histories | FAIL | |
| O1 | Observability scheduled loop | BLOCKED | Cron owned by Codex |
| X1 | Consumer UX, composer attachments, speech | PARTIAL | |
| K1 | Performance measurements | NOT TESTED | |
| D1 | Preview + authenticated browser matrix | PARTIAL | CORS repaired; product flows not accepted |

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

## Next unfinished task

If interrupted: commit/push this branch, then isolated markets/collections demo (M1) without seeding production `sujalthapa242`, plugin catalog live check, authenticated preview acceptance. Cron still owned by Codex.
