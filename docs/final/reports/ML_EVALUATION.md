# Evidence-learning evaluation

This report records one new experiment: whether a forecast of Open University module completion gets better as more of that registration's own activity is allowed in. It does not restate the pooled OULAD bake-off or the shared-200 comparison against an LLM.

Measured output: `benchmarks/oulad_completion_v1/evidence_learning_v1.json`.

## Dataset

Official anonymised OULAD archive, downloaded by `scripts/download_oulad.py` from figshare file `8606371` and checked against MD5 `7412686fd77cf0e0ee1e8c3e9b354308`. Citation: Kuzilek, Hlosta, and Zdrahal, Scientific Data 4:170171 (2017), doi:10.1038/sdata.2017.171. The paper states the dataset is available under CC BY 4.0. Figshare record: doi:10.6084/m9.figshare.5081998.

Outcome, unchanged from `benchmarks/oulad_completion_v1/benchmark_manifest.json`: Pass or Distinction versus Fail or Withdrawn. The same final label is attached to every checkpoint of a registration. A later checkpoint is more evidence about one outcome, not a new outcome.

Features are the existing `oulad-temporal-v1` frame. VLE clicks and assessment submissions are limited to dates on or before the checkpoint inside `oulad_benchmark.py`. This pass does not rebuild that filter. Half-life 14 is reused from the earlier validation selection. It was not tuned again.

Student splits are the existing SHA-256 split at seed `20260828` (`stable_split`). No test student is in train.

| Split | Students | Checkpoint rows |
| --- | ---: | ---: |
| Train | 17,258 | 78,120 |
| Validation | 4,306 | 19,604 |
| Calibration | 4,299 | 19,396 |
| Test | 2,922 | 13,252 |

Each test checkpoint has 3,313 rows. That is larger than 2,922 because some held-out students have more than one module registration, and the split keeps every registration of a student together. Metrics below treat registrations as rows.

Train completion rate: 0.4701. Test completion rate at every checkpoint: 0.4739.

## What was reused

- `build_model` logistic regression and histogram gradient boosting, with the existing feature columns at half-life 14.
- `ProbabilityCalibrator`. Platt versus isotonic is chosen by Brier on even/odd rows of the calibration split, then the chosen method is refit on the whole calibration split. Test rows are not used for that choice. Selected methods: static logistic isotonic, evidence logistic isotonic, boosting Platt.
- `brier_score`, `log_loss`, `expected_calibration_error`, and `roc_auc_score`. AUC is omitted, not reported as 0.5, when the score or the outcome does not vary.
- `logistic_contributions` for one redacted explanation. Those contributions are the pre-calibration linear terms. They are not the calibrated probability.
- The checkpoint list 14, 35, 70, 105 and the activity aggregation that drops events after the checkpoint.

## What is new

`evaluation/evidence_learning.py` scores the same held-out registrations at each checkpoint:

- Population prior: the train completion rate, constant.
- Static covariates: calibrated logistic on module, presentation, previous attempts, studied credits, and presentation length. No activity features.
- Evidence logistic: calibrated logistic on the existing half-life-14 feature set.
- Shrunk evidence: that logistic probability blended toward the train rate with weight `n / (n + strength)`. `n` is an exposure score, `submissions + log1p(active_days)`, not a design-based effective sample size. Strength is chosen from `{1, 2, 4, 8, 16, 32}` by minimum validation Brier.
- Existing boosting family, calibrated, as the trained ML comparison.

Sufficiency labels, used only for slicing and explanation: `population_only` when both counts are zero, `sparse` when the exposure score is below 2, otherwise `adequate`. The feature builder fills missing activity with 0 before this module runs, so a student with no log rows and a student with measured zeros are the same input on OULAD. The NaN path is covered by unit tests and is not what this curve sees.

`applies_to` is true only for `oulad_module_completion`.

## Held-out results

Brier on the 3,313 test rows at each checkpoint. Lower is better. Full precision is in the JSON.

| Day | Prior | Static | Evidence logistic | Shrunk | Boosting |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 14 | 0.2493 | 0.2379 | 0.2031 | 0.2216 | 0.1865 |
| 35 | 0.2493 | 0.2379 | 0.1653 | 0.1951 | 0.1531 |
| 70 | 0.2493 | 0.2379 | 0.1266 | 0.1612 | 0.1181 |
| 105 | 0.2493 | 0.2379 | 0.1058 | 0.1407 | 0.0964 |

Log loss, same rows:

| Day | Prior | Static | Evidence logistic | Shrunk | Boosting |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 14 | 0.6918 | 0.6683 | 0.5939 | 0.6341 | 0.5508 |
| 35 | 0.6918 | 0.6683 | 0.4965 | 0.5761 | 0.4582 |
| 70 | 0.6918 | 0.6683 | 0.3934 | 0.4969 | 0.3648 |
| 105 | 0.6918 | 0.6683 | 0.3370 | 0.4455 | 0.3028 |

AUC and 10-bin ECE. The constant prior has no AUC.

| Day | Logistic AUC | Boosting AUC | Logistic ECE | Boosting ECE | Shrunk ECE |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 14 | 0.750 | 0.789 | 0.0391 | 0.0188 | 0.0961 |
| 35 | 0.841 | 0.856 | 0.0558 | 0.0182 | 0.1236 |
| 70 | 0.899 | 0.909 | 0.0348 | 0.0134 | 0.1340 |
| 105 | 0.928 | 0.937 | 0.0335 | 0.0103 | 0.1300 |

Static metrics do not change across days. That is the expected check that the static model is not reading activity.

Mean exposure score on the test rows rises from 1.54 at day 14 to 5.10 at day 105. The share of rows with no submissions and no active days falls from 0.192 to 0.133.

## Where evidence helped

On the full test slice, both the evidence logistic and boosting improve at every later checkpoint. From day 14 to day 105, logistic Brier falls by 0.0973 and boosting Brier falls by 0.0902. Boosting is the best of the five scores at every checkpoint, and its ECE falls from 0.0188 to 0.0103.

The people who already have activity are the right place to look for "more evidence about this registration." On the `adequate` slice the evidence-logistic Brier moves from 0.2068 (day 14, n=1,194, completion rate 0.699) to 0.1306 (day 105, n=2,624, completion rate 0.595). AUC on that slice moves from 0.651 to 0.886. Completion rate in the slice is not rising; the forecasts are getting sharper.

Static covariates beat the prior by 0.0115 Brier and reach AUC 0.620. That is the population-level part. Activity features account for the rest of the gain.

## Where the new shrinkage rule failed

Validation Brier of the shrunk logistic rose monotonically with prior strength: 0.1848, 0.1901, 0.1991, 0.2110, 0.2233, 0.2335. The selected strength is 1, the weakest candidate. On the test slice that blend is still worse than the unshrunk calibrated logistic at every checkpoint, on Brier, log loss, AUC, and ECE.

The one slice where shrinkage lowered Brier is day-14 `sparse` (n=1,484): 0.2271 versus 0.2316 for the logistic, with ECE 0.0405 versus 0.0740. At days 35, 70, and 105 the same blend is worse on the sparse slice. It is worse on every adequate slice.

Rows with no recorded submissions or active days are not "no information." Their completion rate is 0.117 at day 14 (n=635) and 0.009 at day 105 (n=441). The logistic uses the zero activity counts and the covariates; its Brier on that slice is 0.1296 at day 14 and 0.0096 at day 105. Shrinkage replaces those probabilities with the train rate 0.4701, so its Brier equals the prior (0.2280 and 0.2215) and its ECE on the day-105 slice is 0.461. The day-105 Brier looks small because almost nobody in that slice completes. AUC there is only 0.630, so this is not fine-grained ranking of four completers.

Shrinkage was not recalibrated after the blend. That is one reason ECE gets worse. It is also the wrong direction for this outcome: inactivity is associated with non-completion. The association is not an effect of an intervention.

## Explanation check

One redacted test registration is walked across checkpoints in the JSON. Student id is omitted. Calibrated logistic probability moves 0.6326, 0.7686, 0.7913, 0.9111 as recorded observations go from 10 to 48. The shrunk values are 0.5848, 0.7089, 0.7421, 0.8548, and each matches `n / (n + 1)` times the model probability plus the rest times the prior. `causal_claim` is null.

The largest pre-calibration term at day 14 is `assessment_weighted_score_sum` at -1.771 log-odds. At day 105 the same term is +5.483. Those terms explain the linear predictor before calibration. They do not add up to the calibrated probability. One registration is not a population result.

## Relation to older OULAD numbers

Previously published, and not a result of this pass:

- Pooled prevalence Brier on 13,252 test rows: 0.249326 in `evaluation_results.json`. The constant train-rate Brier in this experiment is 0.249333. They are close because the train and test completion rates are close. This pass does not replace that file.
- Pooled calibrated boosting Brier: 0.137827. The unweighted mean of this pass's four checkpoint boosting Briers is 0.1385. The gap is consistent with refitting calibration rather than replaying the frozen artifact. It is not a claim of a better pooled model.
- Shared-200 LLM Brier 0.2228 is an older comparison on 200 rows. It was not rerun. No paid model call was made.

## Reproducibility

```text
uv run python scripts/download_oulad.py
uv run python scripts/evaluate_evidence_learning.py
uv run python -m pytest apps/api/tests/test_evidence_learning.py apps/api/tests/test_oulad.py
```

If `data/oulad/raw/studentInfo.csv` and `studentVle.csv` are absent, the evaluator prints `not_executed` and exits 2 without writing a result file. Seed `20260828`. Two runs of `learning_curve` on the synthetic fixture match. The OULAD command was run twice after the metric code settled; the checkpoint Briers matched to the printed precision.

## Boundaries

This fit does not apply to hiring, running, finance, startup outcomes, or to a live personal goal. No production user data was used. No confidence interval on the Brier difference was computed. Training still sees later checkpoints of other students; only the scored student's future clicks are excluded. Rows that share a student are not independent.
