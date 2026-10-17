# Hackathon Proof Table

## WHAT WE HAVE EMPIRICALLY PROVEN
- On the frozen OULAD shared-200 education goal-pricing benchmark (n=200), Play It Out Brier 0.157994 vs raw GPT 0.222799 (29.1% relative Brier reduction); paired bootstrap P(Δ>0)=1.000.
- Selected numerical model also beats the logistic statistical baseline on the same shared-200 cases (Brier 0.157994 vs 0.172964).
- As evidence accumulates toward resolution, Play It Out Brier improved 27.2% (day-14 0.1829 → day-105 0.1332) while raw GPT improved 16.8% (0.2279 → 0.1897).
- Evidence decay ablation selected half-life=14d on validation before test (hist GB).
- CRN reduced uplift estimator variance by 25.1% (ratio 0.749).
- Raw GPT invents success probabilities on 100% of Goal Architect cases (n=8); structured Goal Architect schema-valid 100% with invented-probability-field rate 0%.
- Evidence Agent (n=7) hallucinated-probability rate 0% vs raw GPT odds-assignment rate 100%; event-count match 100%.
- Intervention Agent (n=14) unsupported/NOT_PRICED rate 86%; raw GPT invents numeric uplift on 100% of forced-uplift prompts.
- Source Planner (n=6) mean NDCG@5 0.987; mean precision 0.892; irrelevant-plugin rejection 100%.
- Forecast Critic frozen suite accuracy 100% (leakage recall True; LLM_GENERATED_COEFFICIENT recall True).
- Model-consistent career policy selection under a 20h budget produced regret_vs_oracle=0.0 (not a causal real-world claim).

## WHAT REMAINS UNVALIDATED
- Macro-average Brier across career/finance/running/startup/habits — no resolved outcome labels yet.
- Real-world causal action-effect MAE / ATE validation — no randomized/quasi-experimental personal action panel loaded.
- Domains-won K/K pricing claim — only education currently has resolved labels.
- Cold browser Goal Architect→Paths matrix for every family from empty state — still pending full interactive run.
- Raw-GPT Source Planner NDCG head-to-head on the expanded resource-level set — current probe scores Play It Out planner only.

## GOAL PRICING (education / OULAD shared-200)

| Metric | Raw GPT | Logistic | Play It Out | Improvement vs GPT |
|---|---:|---:|---:|---:|
| Brier | 0.222799 | 0.172964 | 0.157994 | 29.1% |
| Log loss | 0.637891 | 0.520224 | 0.466617 | — |
| ECE@10 | 0.162750 | 0.111369 | 0.084123 | — |
| AUC | 0.746498 | 0.832555 | 0.860887 | — |

### By domain (resolved pricing labels)

| Domain | n | Raw GPT Brier | Play It Out Brier | Won? |
|---|---:|---:|---:|---|
| Education | 200 | 0.222799 | 0.157994 | Yes |
| Career | — | — | — | no resolved labels |
| Finance | — | — | — | no resolved labels |
| Running | — | — | — | no resolved labels |
| Startup | — | — | — | no resolved labels |
| Habits | — | — | — | no resolved labels |
| **Macro average** | — | — | — | **not computable** |

## LONGITUDINAL PRICING

- Play It Out relative Brier improvement day14→105: 27.2%
- Raw GPT relative Brier improvement day14→105: 16.8%
- Selected evidence decay half-life: 14 days

## ACTION / POLICY (model-consistent, non-causal)

- Policy value uplift: 0.15192855033269304
- Regret vs oracle: 0.0
- Constraint violations: 0

## AGENTS

- Goal Architect raw prob claim rate: 1.0
- Goal Architect schema valid: 1.0
- Evidence F1-proxy (event-count match): 1.0
- Evidence hallucinated probability rate: 0.0
- Source Planner mean NDCG@5: 0.9871053543552266
- Source Planner mean precision/recall: 0.8916666666666666 / 1.0
- Intervention unsupported/NOT_PRICED rate: 0.8571428571428571
- Critic suite accuracy: 1.0

## MONTE CARLO / CRN

- Converged: True; draws 6000; MC error 0.00639499804534763
- CRN variance ratio: 0.7493107099526674; variance reduction 25.1%

Artifact: `benchmarks/hackathon_proof_v1/results.json`
Domain inventory: `C:/Users/sujal/hackathons/playitout-pass5/benchmarks/hackathon_proof_v1/domain_inventory.json`
