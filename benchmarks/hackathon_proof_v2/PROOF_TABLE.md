# Hackathon Proof Table v2

Brier one-liner: *Brier measures how close predicted probabilities were to what actually happened; lower is better and confident wrong predictions are penalized heavily.*

## WHAT WE HAVE EMPIRICALLY PROVEN
- Multi-domain resolved pricing on **4** goal families (education, finance, running, career).
- Macro Brier GPT `0.132` → PIO `0.110` (16.5% lower macro probability error); PIO won **3/4** domains on Brier.
- Education (kept): GPT `0.223` → PIO `0.158` (29.1% lower error).
- Finance SHED panel: GPT `0.192` → PIO `0.167` (12.9% lower error) on n=40 shared forecasts.
- Career JTH: Brier nearly tied (`0.101` vs `0.100`) but AUC `0.660` → `0.729` on rare offers.
- Running volume full-test: prevalence Brier 0.244 → HGB 0.062; longitudinal error falls as year progresses (Mar 0.101 → Jun 0.056 → Sep 0.028). Decay ablation ~0.3% — **not claimed** for this domain.
- OULAD longitudinal (v1): PIO Brier improved 27.2% day14→105 vs GPT 16.8%.

## WHAT REMAINS UNVALIDATED / LOST
- Running shared-40 GPT head-to-head: **GPT won** (near-ceiling volume features).
- Habits & startup: no strongly validated public resolved panels loaded this pass.
- Causal action-effect MAE against randomized personal interventions: not loaded (Pune savings RCT blocked 403; model-consistent What If remains non-causal).
- Agent subsystems expanded toward larger frozen sets; live GPT head-to-heads still limited by cost.

## PROOF TABLE (technical + human)

| What are we proving? | GPT | Play It Out | Improvement | What this means |
|---|---:|---:|---:|---|
| Goal probability error (macro across 4 domains) | 0.132 | 0.110 | -16.5% | Our odds were closer to reality on average across education/finance/running/career |
| Education probability error (OULAD shared-200) | 0.223 | 0.158 | -29.1% | 29% lower probabilistic forecasting error than GPT on resolved course-completion forecasts |
| Finance probability error (SHED emergency funds) | 0.192 | 0.167 | -12.9% | 12.9% lower probabilistic forecasting error than GPT on the same resolved forecasts. |
| Career probability error (JTH offer) | 0.101 | 0.100 | -0.7% | Small Brier edge in a ~2% base-rate offer setting; AUC 0.66→0.73 |
| Running probability error (1500km volume, March ck sample) | 0.011 | 0.014 | -29.0% | GPT edged PIO on a near-ceiling sample (both AUC=1.0). Not claimed as a domain win. |
| Education calibration error (ECE) | 0.163 | 0.084 | -48.3% | When we say ~70%, outcomes behave more like ~70% |
| Domains won (Brier) | 1/4 GPT | 3/4 PIO | +2 domains | Play It Out beat GPT in 3/4 domains and reduced macro probability error by 16.5%. |

## BY DOMAIN (shared GPT comparison)

| Domain | n | GPT Brier | PIO Brier | Δ% | Won? |
|---|---:|---:|---:|---:|:---:|
| Education | 200 | 0.223 | 0.158 | 29.1% | Yes |
| Finance | 40 | 0.192 | 0.167 | 12.9% | Yes |
| Running | 40 | 0.011 | 0.014 | -29.0% | No |
| Career | 40 | 0.101 | 0.100 | 0.7% | Yes |
| **Macro** | — | **0.132** | **0.110** | **16.5%** | **3/4** |

## FULL-TEST STATISTICAL (no GPT cost)

- SHED test n=374: prevalence `0.249` → HGB `0.130` (AUC `0.889`).
- Running volume test n=10932: prevalence `0.244` → HGB `0.062`.
- JTH offer test rows=24390: HGB Brier `0.0202`, AUC `0.699` (base rate ~2%).

## AGENTS (from prior frozen suites; see expansion artifacts)

- Goal Architect / Evidence / Intervention / Source / Critic metrics retained from `hackathon_proof_v1` unless superseded by `agent_cases_v2` reruns.
- Intervention unsupported honesty and critic defect recall remain core product claims.

Artifact: `benchmarks/hackathon_proof_v2/pricing_results.json`
Frozen assembly timestamp: 2026-08-30T19:10:26.559333+00:00
