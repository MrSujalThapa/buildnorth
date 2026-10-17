# Judge Summary — Play It Out Hackathon Proof v2

Across four types of resolved goals, our odds had **16.5% less probability error than GPT-5.4**. Play It Out won **3 of 4** tested goal families.

The technical measure is macro Brier score (lower is better): GPT-5.4 `0.132` → Play It Out `0.110` on the same cases and information.

On education, Play It Out reduced probability error by **29.1%**. As evidence accumulated, its forecasts improved **27.2%**, versus **16.8%** for GPT.

## What did the system do differently?

Agents interpreted goals, selected evidence sources, normalized records, structured research, translated actions, and challenged receipts. Versioned numerical models—not LLM prose—owned the probabilities. Unsupported effects were withheld instead of guessed.

## Do the probabilities mean anything?

Brier measures how close predicted probabilities were to what actually happened; lower is better and confident wrong predictions are penalized heavily.

On education, calibration error (ECE) fell from 0.163 to 0.084. When Play It Out says something has roughly a 70% chance, those ~70% forecasts should happen roughly 70% of the time — and they match reality more closely than raw GPT.

## Does evidence actually improve the forecast?

On OULAD checkpoints, Play It Out’s forecast error fell **27.2%** from day 14 to day 105 as course evidence arrived, versus **16.8%** for GPT. On running volume, error fell from March→September as more of the year’s training was observed (full-test HGB Brier 0.101 → 0.028 by checkpoint).

## What did action planning show?

In the product simulator, the hours-budgeted policy captured **95% of modeled available upside**, versus **55%** for equal allocation. This is simulator/model-consistent, **not a causal real-world treatment-effect claim**.

## Can it find the right personal evidence?

On the expanded labeled resource suite, Source Planner selected the correct resource first **79% of the time** (NDCG@5 0.97). The suite is frozen and hand-labeled, not a live-provider leaderboard.

## Does it hallucinate?

From frozen agent suites: when effects are unsupported, structured Intervention Agent returns NOT_PRICED/ASSUMPTION paths at high rates while raw GPT invents numeric uplifts when forced. Critic catches leakage and invented coefficients in the frozen defect suite.

## Honest caveats

- Running GPT head-to-head sample: GPT slightly better on a near-ceiling volume task.
- Career offers are rare (~2%); ranking (AUC) is more informative than raw Brier.
- Habits/startup lack strong public resolved panels here.
- No fabricated labels, coefficients, or wins.

Sources: [`pricing_results.json`](pricing_results.json), [`PROOF_TABLE.md`](PROOF_TABLE.md), and the OULAD/JTH/SHED/running benchmark manifests. Offline verification: `uv run python scripts/verify_frozen_proof.py`.
