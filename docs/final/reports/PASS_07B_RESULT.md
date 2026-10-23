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

## 5. API evidence, inference, and publication

`POST /api/v1/goals/{goal_id}/evidence/manual` on an agent-created SWE offer goal:

1. Ten applications publish a priced forecast (`REFERENCE_MODEL` on the service path).
2. Two recruiter responses and eight application rejections publish a different probability (`FITTED_STATISTICAL`).
3. Submitting those same two rows again returns `reprice_status: unchanged`, and the evidence list still has one rejection row with value 8.

The receipt fields are asserted on `BaselineForecastService`, which is the service that endpoint calls. `GET /api/v1/what-if/history/{goal_id}` in the isolated test app reads the What If simulation repository, not that baseline store, so this test does not use it as proof of publication.

## 6. Before and after

Fixture deadline is 180 days after the run. On 2026-10-23 the service returned:

- 10 applications, reference rate 0.12: probability **0.110010**, method `REFERENCE_MODEL`.
- Same applications, 2 responses, 8 application rejections: fitted rate **0.164444…** = `(2 + 8 * 0.12) / 18`, probability **0.169858**, method `FITTED_STATISTICAL`.

Those probabilities move if the deadline moves. The rate formula does not. The API test checks that the two published probabilities differ and that a duplicate submission does not. Practice hours left the probability unchanged.

## 7. Tests and CI

Passed locally:

- `apps/api/tests/test_hiring_model.py`
- `apps/api/tests/test_manual_evidence_api.py` including the new workflow
- `apps/api/tests/test_baseline_reprice.py`

Ruff: no new findings. Architecture check passed. Mypy on `selection.py` and `hiring.py` is clean. `check_mypy_baseline.py` still reports the pre-existing errors in gitignored `scripts/_phase0_*.py`, which are not in the CI checkout.

Full GitHub Actions (Postgres, the whole suite, web build) was not run. Local Python is 3.14. CI is 3.12.

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
