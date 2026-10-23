# Pass 07B result — live prediction methods

Branch `feat/pass-07b-live-ml`, from `origin/main` at `4dcb523`. Not merged. Not deployed. This branch does not contain Pass 06 (draft PR #18), Pass 07A (draft PR #19), or the uncommitted course-grade work on `feat/playitout-next-pass`.

No trained classifier was connected to a live goal. None of the evaluated classifiers has both a matching outcome and features the product can collect. The live path that now updates from evidence is the existing hiring funnel, with stage rates fit from resolved passes and rejections.

## 1. Trained models connected to application code

None. `forecasting/selection.py` records why each shipped evaluation stays off:

| Model | Outcome it was trained on | Why it is not applied |
| --- | --- | --- |
| `oulad_completion_v1` | Module Pass/Distinction versus Fail/Withdrawn | Needs OULAD VLE clicks and assessments at days 14, 35, 70, or 105. A personal goal does not collect that schema. |
| `jth_offer_v1` | One JTH application row receives an offer | Needs that dataset's candidate and job fields and stage dates. A hiring goal here is the user's own funnel counts. Source license is CC BY-NC. No artifact is loaded. |
| `shed_emergency_savings_v1` | SHED `EF1` is Yes in 2023 | Needs 2022 survey codes, not a balance and a contribution. |
| `running_pace_improve_2019_v1` | Second-half 2019 mean pace is at least 5% faster | A race-time goal is a threshold on the user's own timed efforts. The existing trend fit is used instead. |

`trained_classifier` on a receipt is null. No model file is loaded, and no probability comes from an LLM.

## 2. Which goals use which method

`BaselineForecastService.compute` writes a `prediction` block on every receipt.

- Hiring goal with at least one recorded rejection at a stage: `FITTED_STATISTICAL`. The rate is `(successes + 8 * prior) / (successes + failures + 8)`. The 8 pseudo-counts are `resolved_outcome_pseudo_counts` in `data/reference/hiring_funnel_rates.json`. In-flight applications are not treated as failures.
- Hiring goal with applications but no resolved rejection: `REFERENCE_MODEL`. Stage rates stay the frozen reference.
- Hiring goal with an observed offer: `DETERMINISTIC` only as a label for the existing 0.995 observed-offer ceiling. That ceiling was not changed.
- Finance goals: `REFERENCE_MODEL`. The balance and contribution are the user's; the return distribution is the reference. It is not the SHED classifier.
- Running goals whose pace trend comes from the user's own efforts: `FITTED_STATISTICAL` via the existing running estimator, not the 2019 classifier.
- A goal the numerical model cannot price: `NOT_PRICED`. Missing numbers are not filled in.

## 3. What still uses statistical or Monte Carlo models

Savings paths still use the finance reference distribution. Running thresholds still use the pace trend and measurement noise. Habits, startup scenarios, and composed primitives are unchanged. The Monte Carlo engine was not rewritten.

## 4. Feature requirements and limits

Hiring fit uses application, response, phone-screen, OA, technical, final, and offer counts, plus rejections tagged to a stage. A stage with no rejection keeps its reference rate and is listed in `missing_inputs`. Practice hours do not change the probability. Parallel applications are treated as independent. The shrinkage is not a posterior and is not personal calibration: `calibration.applied` is false and the status is `not_empirically_calibrated`.

Active count at a stage is the cumulative stock, minus people who advanced to the next stage, minus rejections recorded at that same stage, floored at zero. A rejection is not moved to another stage. A count that would go negative is recorded in `stage_count_inconsistencies` and the active count stays zero. Rejections that name no stage stay `unassigned` and are not subtracted anywhere. There is no separate time-based expiry: an in-flight application remains active until it advances or a rejection names its stage. Recency still discounts a stale pipeline; it does not delete unresolved applications.

## 5. API evidence, inference, and publication

`POST /api/v1/goals/{goal_id}/evidence/manual` on an agent-created SWE offer goal:

1. Ten applications publish a priced forecast (`REFERENCE_MODEL`). On 2026-10-23 that API response was 0.171365.
2. Two recruiter responses and eight application rejections publish a different probability (`FITTED_STATISTICAL`). The stored receipt has zero active applications, two active responses, and `future_application_rate` of 2 per week with source `REFERENCE`. The API response was 0.231615.
3. Submitting those same two rows again returns `reprice_status: unchanged`, and the evidence list still has one rejection row with value 8.

The receipt fields are on the forecast stored by `BaselineForecastService`, which is the service that endpoint calls. `GET /api/v1/what-if/history/{goal_id}` in the isolated test app reads the What If simulation repository, not that baseline store, so this test does not use it as proof of publication.

## 6. Before and after

The first published after-probability counted the 8 application rejections as still active. That figure is kept below as the previous measurement. The active-count fix does not change the fitted rate.

180-day SWE offer fixture, clock and evidence at 2026-10-23, deadline 180 days later. `BaselineForecastService` published:

| State | Active applications | Current pipeline | Future applications (2/week, REFERENCE) | Published probability | Method |
| --- | --- | --- | --- | --- | --- |
| 10 applications | 10 | 0.018622 | 0.093122 | **0.110010** | `REFERENCE_MODEL` |
| 10 applications, 2 responses, 8 application rejections, previous active-count formula | 8 | 0.050825 | 0.125407 | **0.169858** | `FITTED_STATISTICAL` |
| Same evidence, corrected active counts | 0 (2 responses still in flight) | 0.031055 | 0.125407 | **0.152567** | `FITTED_STATISTICAL` |

The corrected 180-day probability is 0.017291 lower than the previously published 0.169858. The applications-only probability is unchanged. Fitted `application_to_response` remains `(2 + 8 * 0.12) / 18` = 0.164444…. The future-application term uses that rate. The current-pipeline term does not keep the rejected applications.

The same evidence was then published through `POST /api/v1/goals/{goal_id}/evidence/manual` on 2026-10-23. The agent-created goal deadline is `2027-08-31T23:59:59Z` (45 weekly periods), so these probabilities are not the 180-day fixture:

| Publication | Active applications | Current pipeline | Future applications (2/week, REFERENCE) | Published probability | Method |
| --- | --- | --- | --- | --- | --- |
| 10 applications | 10 | 0.018622 | 0.155641 | **0.171365** | `REFERENCE_MODEL` |
| 2 responses and 8 application rejections | 0 (2 responses still in flight) | 0.031055 | 0.206988 | **0.231615** | `FITTED_STATISTICAL` |

On that longer horizon the corrected publication is higher than the applications-only publication because expected future applications are priced at the fitted rate. Recomputing the pre-fix active counts (8 applications still treated as active) with the same fitted rate and the same future term gives 0.247293. The corrected API publication is 0.015678 lower than that reconstruction. The receipt's `future_application_rate.source` is `REFERENCE`, `applications_per_week` is 2, and `applies_to` says the rate is not the current pipeline. `calibration.applied` is false. `trained_classifier` is null.

Those probabilities move if the deadline moves. The rate formula and the active-count formula do not. A duplicate submission of the resolved rows returns `reprice_status: unchanged`. Practice hours left the probability unchanged.

## 7. Tests and CI

Local checks on 2026-10-23, using a throwaway Postgres 17 at `127.0.0.1:54329` rather than the developer database:

- Migrations `0001` through `0022` applied. `seed-demo` second run inserted no new rows.
- Ruff baseline: no new findings. Web eslint: 0 errors, 9 existing warnings.
- Web `tsc` and the production build passed. Vitest: 105 tests passed.
- Architecture check passed. Migration sanity passed (22 files).
- `uv run python -m pytest` against that database exited 0. The progress line shows two skips.
- `scripts/evaluate_openai_baseline.py` exited 2, status `not_executed`, `predictions_written` 0, because the frozen OULAD feature artifact is not on this machine. The result file it rewrote was restored and is not in this change.
- `check_mypy_baseline.py` reports 7 errors, all in gitignored `scripts/_phase0_*.py`. Those files are not in the CI checkout. The mypy baseline was not edited.

Python here is 3.14. CI is 3.12. GitHub Actions run [40036188816](https://github.com/MrSujalThapa/buildnorth/actions/runs/40036188816) on `8155b1d` completed with success. PR #20 stayed a draft.

## 8. Integration dependencies

- Publication still goes through `BaselineForecastService` and `BaselineRepriceService`.
- The hiring prior file now has `resolved_outcome_pseudo_counts`. Older files without that key default to 8.
- Pass 07A's checkpoint evaluator is not on this branch and is not imported.
- Do not point this funnel at JTH, OULAD, SHED, or the pace classifier without a new feature schema and a new evaluation.

## 9. Goals that still cannot be priced

- Hiring goals with no applications, interviews, offers, or rejections.
- Course-completion goals that do not have the OULAD checkpoint schema. The classifier is rejected rather than run on the title.
- What If actions that are not a parameter of the priced model. Practice and "study more" do not invent a completion effect. The existing unmapped path returns `NOT_PRICED`.
- Any goal whose family is missing required numeric inputs.

## 10. Conflicts

No files from Codex's course-grade remediation or from PR #18 or PR #19 were edited. Those branches should not be rebased onto this one casually: this work starts at `4dcb523` and they do too, but their commits are not here.
