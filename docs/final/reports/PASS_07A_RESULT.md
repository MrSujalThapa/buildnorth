# Pass 07A result — evidence-driven learning

Branch `feat/pass-07-ml-learning`, cut from `origin/main` at `4dcb523`. Not merged. Not deployed. This branch does not contain Pass 06 (`feat/pass-06-personal-agents`, draft PR #18) or the uncommitted course-grade work on `feat/playitout-next-pass`.

The question this pass measured: does a completion forecast get better as more of a person's own recorded activity is included? The answer, on OULAD only, is yes for the existing calibrated logistic and boosting models, and no for a new blend that pulls those probabilities toward the train completion rate.

Full tables, sample sizes, and the redacted explanation are in `docs/final/reports/ML_EVALUATION.md` and `benchmarks/oulad_completion_v1/evidence_learning_v1.json`.

## Implemented

New, and not wired into live goal creation, evidence ingestion, What If, or MCP:

- `apps/api/src/personal_markets/evaluation/evidence_learning.py`
- `apps/api/tests/test_evidence_learning.py`
- `scripts/evaluate_evidence_learning.py`

Reused without modification: `forecasting/models.py` (`build_model`, `ProbabilityCalibrator`, `feature_columns`, `logistic_contributions`), `evaluation/metrics.py`, `evaluation/oulad_benchmark.py` (`build_feature_frame`, `stable_split`), and the published split in `benchmark_manifest.json`. The Monte Carlo engine was not changed.

The statistical contract on an explained forecast is:

- domain `oulad_module_completion`, and `applies_to` is false for every other domain
- population prior (train completion rate) and the calibrated model probability, kept separate
- shrunk probability, which must match the exposure-score formula or the explainer raises
- observation count, exposure score, sufficiency (`population_only`, `sparse`, `adequate`)
- prior strength, calibration status, model version `evidence-learning-v1`, dataset id `oulad_completion_v1`
- pre-calibration log-odds, labeled as such
- `causal_claim: null`

The exposure score is `submissions + log1p(active_days)`. It is not a posterior effective sample size. Parameter uncertainty is not a Bayesian posterior; the strength grid is a regularizer. Calibration status on these fits is `calibration_split`. There is no personalized calibration claim.

## Measured

Official OULAD, CC BY 4.0 as stated by Kuzilek, Hlosta, and Zdrahal, Scientific Data 4:170171 (2017). Archive MD5 `7412686fd77cf0e0ee1e8c3e9b354308`. Seed `20260828`. Test students 2,922, disjoint from train. Test rows per checkpoint 3,313.

Held-out Brier:

| Day | Prior | Static covariates | Evidence logistic | Shrunk toward prior | Boosting |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 14 | 0.2493 | 0.2379 | 0.2031 | 0.2216 | 0.1865 |
| 35 | 0.2493 | 0.2379 | 0.1653 | 0.1951 | 0.1531 |
| 70 | 0.2493 | 0.2379 | 0.1266 | 0.1612 | 0.1181 |
| 105 | 0.2493 | 0.2379 | 0.1058 | 0.1407 | 0.0964 |

Boosting remains the best score at every checkpoint. Its ECE improves from 0.0188 to 0.0103. The evidence logistic also improves at every later checkpoint. Static covariates do not, which is the check that they ignore activity.

On registrations that already have enough recorded activity for the `adequate` label, evidence-logistic Brier moves from 0.2068 at day 14 (n=1,194) to 0.1306 at day 105 (n=2,624). That is the personal-evidence gain.

Shrinkage did not help overall. Validation Brier got worse at every stronger prior, so the grid selected strength 1. Test Brier, log loss, AUC, and ECE are all worse than the unshrunk logistic at every checkpoint. The single favorable slice is day-14 sparse rows (n=1,484), Brier 0.2271 versus 0.2316. Pulling zero-activity rows back to the 0.4701 train rate discarded a real association: those rows complete at 0.117 by day 14 and at 0.009 by day 105. That association is not a causal effect of inactivity.

The previously published pooled boosting Brier of 0.1378 and the shared-200 LLM Brier of 0.2228 are older experiments. They were not rerun and are not Pass 07A findings. No paid API call was made.

## Tests

`uv run python -m pytest apps/api/tests/test_evidence_learning.py apps/api/tests/test_oulad.py` — 14 passed.

Covered: zero and missing counts, shrinkage bounds, explanation identity and a null causal claim, domain applicability, duplicate checkpoint rows, a student placed in both train and test, outcome columns banned from inputs, identical reruns, later evidence lowering Brier on the synthetic fixture, no invented AUC for a constant score, and the known Brier of 0.25 for probability 0.5 on an outcome of 1. The existing OULAD fixture test still checks that a click after the checkpoint does not enter `vle_total_clicks`.

`scripts/check_ruff_baseline.py`: no new findings. `mypy` on the new module, its test, and the script: clean. `scripts/check_architecture.py`: passed.

Not run: the full GitHub Actions job (Postgres 17, the whole pytest suite, npm lint, typecheck, web build, migrations, seed). This change does not touch those paths. Local Python is 3.14; CI is 3.12.

## Integration dependencies

Safe to merge only after review, and not onto live goals:

- The evaluator imports the existing forecasting model builders and the OULAD feature builder. It does not publish a receipt or update a goal.
- `applies_to("oulad_module_completion")` is the gate. Hiring, running, finance, and startup must stay outside it.
- A later product integration would need to keep the feature-time cutoff, the student-level split, and the calibration split. Copying these coefficients onto a personal goal would be a new experiment, not this result.
- Pass 06 and the course-grade remediation are separate branches. This work does not depend on them and must not be mixed into them by a rebase that drops their commits.

## Limitations

- One module-completion label is repeated across checkpoints.
- Training sees other students' later checkpoints.
- Registrations that share a student are not independent, and no Brier interval was computed.
- Missing activity in the OULAD frame is already filled with 0, so absence and a measured zero are not distinguished here.
- The exposure score and the sparse cutoff of 2 are definitions, not estimated sample sizes.
- Shrinkage is not a posterior and was not recalibrated.
- The explained log-odds are pre-calibration.
- No production data, no live forecast publication, no Render, Vercel, cron, or credential change.
