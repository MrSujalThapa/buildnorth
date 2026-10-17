"""Fair GPT vs Play It Out pricing on frozen shared subsets across domains.

Uses identical feature dicts for GPT and the numerical systems. Caches GPT replies.
Respects PM_OPENAI_MAX_COST_USD.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from personal_markets.agents.budget import InMemoryUsageStore, TokenBudget
from personal_markets.agents.models import estimate_cost_usd
from personal_markets.core.config import get_settings
from personal_markets.evaluation.judge_translations import (
    domain_pricing_card,
    translate_auc,
    translate_brier,
    translate_calibration_bins,
    translate_ece,
)
from personal_markets.evaluation.metrics import (
    brier_score,
    calibration_bins,
    expected_calibration_error,
    log_loss,
    paired_bootstrap_brier,
)
from personal_markets.integrations.openai import OpenAIInferenceProvider
from personal_markets.ports import InferenceRequest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "benchmarks" / "hackathon_proof_v2"
CACHE = ROOT / ".artifacts" / "multidomain_gpt_cache"
SEED = 20260830


def score(y: list[int], p: list[float]) -> dict[str, Any]:
    clipped = [min(max(v, 1e-6), 1 - 1e-6) for v in p]
    out: dict[str, Any] = {
        "n": len(y),
        "brier": brier_score(y, clipped),
        "log_loss": log_loss(y, clipped),
        "ece_10": expected_calibration_error(y, clipped),
        "mean_p": float(np.mean(clipped)),
        "base_rate": float(np.mean(y)),
    }
    try:
        from sklearn.metrics import roc_auc_score

        out["roc_auc"] = float(roc_auc_score(y, clipped))
    except ValueError:
        out["roc_auc"] = None
    bins = calibration_bins(y, clipped, 10)
    out["calibration_bins"] = [
        {
            "lower": b.lower,
            "upper": b.upper,
            "count": b.count,
            "mean_probability": b.mean_probability,
            "observed_rate": b.observed_rate,
        }
        for b in bins
    ]
    return out


def _provider() -> OpenAIInferenceProvider:
    settings = get_settings()
    budget = TokenBudget(
        InMemoryUsageStore(),
        settings.openai_daily_token_budget_high_volume,
        settings.openai_daily_token_budget_premium,
        settings.openai_max_cost_usd,
    )
    return OpenAIInferenceProvider(
        api_key=settings.openai_api_key or "",
        default_model=settings.openai_baseline_model,
        budget=budget,
        timeout_seconds=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
        max_output_tokens=80,
    )


async def gpt_probability(provider: OpenAIInferenceProvider, model: str, goal: str, features: dict[str, Any]) -> float:
    key = hashlib.sha256(f"{model}|{goal}|{json.dumps(features, sort_keys=True, default=str)}".encode()).hexdigest()
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{key}.json"
    if path.exists():
        return float(json.loads(path.read_text(encoding="utf-8"))["probability"])
    request = InferenceRequest(
        instructions=(
            "Estimate the probability that the described personal goal resolves YES. "
            "Use only the supplied features available at prediction time. "
            "Return one JSON object matching the schema. Do not invent evidence."
        ),
        input={"goal": goal, "features_at_prediction_time": features},
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["probability"],
            "properties": {"probability": {"type": "number", "minimum": 0, "maximum": 1}},
        },
        model=model,
        pool="premium",
        agent_name="baseline",
    )
    response = await provider.complete_structured(request)
    probability = float(response.structured_output["probability"])
    path.write_text(json.dumps({"probability": probability, "model": response.model}), encoding="utf-8")
    return probability


def load_education_shared() -> dict[str, Any]:
    shared = json.loads(
        (ROOT / "benchmarks/oulad_completion_v1/shared_200_comparison_v1.json").read_text(encoding="utf-8")
    )
    # Prefer already-scored arms from hackathon_proof_v1
    v1 = json.loads((ROOT / "benchmarks/hackathon_proof_v1/results.json").read_text(encoding="utf-8"))
    pricing = v1["goal_pricing"]
    gpt = pricing["arms"]["A_raw_gpt"]
    pio = pricing["arms"]["G_play_it_out_calibrated_numerical"]
    return {
        "domain": "education",
        "dataset": "oulad_completion_v1",
        "n": pricing["n_shared"],
        "goal": "Course completion (Pass/Distinction) by presentation end",
        "gpt": gpt,
        "pio": pio,
        "logistic": pricing["arms"]["C_logistic_statistical"],
        "relative_brier_reduction_vs_gpt": pricing["relative_brier_reduction_vs_gpt"],
        "paired_bootstrap_vs_gpt": pricing["paired_bootstrap_vs_gpt"],
        "by_horizon": pricing.get("by_horizon"),
        "source": "reuse_hackathon_proof_v1_shared_200",
    }


def sample_rows(frame: pd.DataFrame, n: int, seed: int = SEED) -> pd.DataFrame:
    if len(frame) <= n:
        return frame.copy()
    return frame.sample(n=n, random_state=seed).sort_index()


async def eval_shed(provider: OpenAIInferenceProvider, model: str, n: int) -> dict[str, Any]:
    preds = pd.read_parquet(ROOT / ".artifacts/shed_emergency_savings_v1/test_predictions.parquet")
    panel = pd.read_parquet(ROOT / ".artifacts/shed_emergency_savings_v1/panel.parquet")
    test = panel[panel["split"] == "test"].merge(preds, on="shedid", how="inner")
    sample = sample_rows(test, n)
    goal = "Have emergency/rainy-day funds covering 3 months of expenses by the next annual survey"
    feature_cols = [
        c
        for c in sample.columns
        if c
        not in {
            "shedid",
            "y_ef1_2023",
            "split",
            "y",
            "p_prevalence",
            "p_logistic",
            "p_hgb",
        }
    ]
    gpt_ps: list[float] = []
    for _, row in sample.iterrows():
        feats = {c: (None if pd.isna(row[c]) else row[c]) for c in feature_cols}
        # cast numpy types
        feats = {k: (float(v) if isinstance(v, (np.floating, float, int, np.integer)) else v) for k, v in feats.items()}
        gpt_ps.append(await gpt_probability(provider, model, goal, feats))
    y = sample["y"].astype(int).tolist()
    gpt_s = score(y, gpt_ps)
    pio_s = score(y, sample["p_hgb"].astype(float).tolist())
    log_s = score(y, sample["p_logistic"].astype(float).tolist())
    prev_s = score(y, sample["p_prevalence"].astype(float).tolist())
    boot = paired_bootstrap_brier(y, gpt_ps, sample["p_hgb"].astype(float).tolist(), [str(i) for i in sample["shedid"]], seed=SEED)
    card = domain_pricing_card(
        "finance",
        n=len(y),
        gpt_brier=gpt_s["brier"],
        pio_brier=pio_s["brier"],
        gpt_bins=gpt_s["calibration_bins"],
        pio_bins=pio_s["calibration_bins"],
    )
    return {
        "domain": "finance",
        "dataset": "shed_emergency_savings_v1",
        "n": len(y),
        "goal": goal,
        "gpt": gpt_s,
        "pio": pio_s,
        "logistic": log_s,
        "prevalence": prev_s,
        "relative_brier_reduction_vs_gpt": translate_brier(gpt_s["brier"], pio_s["brier"])["technical"][
            "relative_reduction"
        ],
        "paired_bootstrap_vs_gpt": boot,
        "judge_card": card,
        "translations": {
            "brier": translate_brier(gpt_s["brier"], pio_s["brier"]),
            "ece": translate_ece(gpt_s["ece_10"], pio_s["ece_10"]),
            "auc_pio": translate_auc(pio_s["roc_auc"] or 0.5),
            "calibration_pio": translate_calibration_bins(pio_s["calibration_bins"]),
            "calibration_gpt": translate_calibration_bins(gpt_s["calibration_bins"]),
        },
    }


async def eval_running(provider: OpenAIInferenceProvider, model: str, n: int) -> dict[str, Any]:
    preds = pd.read_parquet(ROOT / ".artifacts/running_volume_2019_v1/test_predictions.parquet")
    # Prefer earliest checkpoint (harder / more forecast-like)
    early = preds[preds["checkpoint_index"] == 0].copy()
    sample = sample_rows(early, n)
    cases = pd.read_parquet(ROOT / ".artifacts/running_volume_2019_v1/cases.parquet")
    feat_cols = [
        "case_id",
        "km_ytd",
        "minutes_ytd",
        "sessions_ytd",
        "active_weeks",
        "km_last_4w",
        "km_last_8w",
        "mean_pace_min_per_km",
        "km_per_day_ytd",
        "projected_km_linear",
        "frac_threshold_ytd",
        "days_elapsed",
        "days_remaining",
        "already_met_by_t",
        "gender",
        "age_group",
        "country",
        "decay_km_hl14",
        "decay_km_hl28",
        "decay_km_hl56",
    ]
    avail = [c for c in feat_cols if c in cases.columns]
    sample = sample.merge(cases[avail], on="case_id", how="left")
    goal = "Accumulate at least 1500 km of logged running distance by 2019-12-31"
    keep = [c for c in avail if c != "case_id"]
    gpt_ps: list[float] = []
    for _, row in sample.iterrows():
        feats = {}
        for c in keep:
            v = row[c]
            if pd.isna(v):
                feats[c] = None
            elif isinstance(v, (np.floating, float)):
                feats[c] = float(v)
            elif isinstance(v, (np.integer, int)):
                feats[c] = int(v)
            else:
                feats[c] = str(v)
        gpt_ps.append(await gpt_probability(provider, model, goal, feats))
    y = sample["y"].astype(int).tolist()
    gpt_s = score(y, gpt_ps)
    pio_s = score(y, sample["p_hgb"].astype(float).tolist())
    log_s = score(y, sample["p_logistic"].astype(float).tolist())
    boot = paired_bootstrap_brier(
        y, gpt_ps, sample["p_hgb"].astype(float).tolist(), [str(i) for i in sample["athlete"]], seed=SEED
    )
    return {
        "domain": "running",
        "dataset": "running_volume_2019_v1",
        "n": len(y),
        "checkpoint": "2019-03-31",
        "goal": goal,
        "gpt": gpt_s,
        "pio": pio_s,
        "logistic": log_s,
        "relative_brier_reduction_vs_gpt": translate_brier(gpt_s["brier"], pio_s["brier"])["technical"][
            "relative_reduction"
        ],
        "paired_bootstrap_vs_gpt": boot,
        "judge_card": domain_pricing_card(
            "running",
            n=len(y),
            gpt_brier=gpt_s["brier"],
            pio_brier=pio_s["brier"],
            gpt_bins=gpt_s["calibration_bins"],
            pio_bins=pio_s["calibration_bins"],
        ),
        "translations": {
            "brier": translate_brier(gpt_s["brier"], pio_s["brier"]),
            "ece": translate_ece(gpt_s["ece_10"], pio_s["ece_10"]),
            "auc_pio": translate_auc(pio_s["roc_auc"] or 0.5),
            "calibration_pio": translate_calibration_bins(pio_s["calibration_bins"]),
            "calibration_gpt": translate_calibration_bins(gpt_s["calibration_bins"]),
        },
        "decay_note": (
            "Decay ablation on full test improved Brier by only ~0.3%; "
            "not claimed as material for this domain."
        ),
    }


async def eval_jth(provider: OpenAIInferenceProvider, model: str, n: int) -> dict[str, Any]:
    from personal_markets.evaluation.jth_benchmark import (
        BenchmarkPaths,
        build_feature_matrix,
        fit_baseline_models,
        _resolve_feature_artifact,
        build_feature_frame,
    )

    paths = BenchmarkPaths(
        raw=ROOT / "data/jth/raw",
        committed=ROOT / "benchmarks/jth_offer_v1",
        artifacts=ROOT / ".artifacts/jth_offer_v1",
    )
    artifact = _resolve_feature_artifact(paths)
    features = pd.read_pickle(artifact) if artifact and artifact.exists() else build_feature_frame(paths.raw)
    # Fit models and score all test rows, then sample for GPT
    metrics = fit_baseline_models(paths)
    x_test, y_test, meta = build_feature_matrix("test", features=features)
    # Reconstruct PIO probs via refit path already done inside fit_baseline_models — use prevalence/logistic from metrics only for GPT shared subset by re-predicting
    from personal_markets.evaluation.calibration_fit import calibrate_prefit
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    x_train, y_train, _ = build_feature_matrix("train", features=features)
    x_val, y_val, _ = build_feature_matrix("val", features=features)
    x_cal, y_cal, _ = build_feature_matrix("cal", features=features)
    x_fit = pd.concat([x_train, x_val], ignore_index=True)
    y_fit = pd.concat([y_train, y_val], ignore_index=True)
    hgb = HistGradientBoostingClassifier(max_depth=6, learning_rate=0.08, max_iter=200, random_state=SEED)
    hgb.fit(x_fit, y_fit)
    p_all = calibrate_prefit(
        hgb,
        np.asarray(x_cal, dtype=float),
        np.asarray(y_cal, dtype=int),
        np.asarray(x_test, dtype=float),
        method="isotonic",
    )
    log_pipe = Pipeline(
        [
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=2000, class_weight="balanced", random_state=SEED)),
        ]
    )
    log_pipe.fit(x_fit, y_fit)
    p_log = calibrate_prefit(
        log_pipe,
        np.asarray(x_cal, dtype=float),
        np.asarray(y_cal, dtype=int),
        np.asarray(x_test, dtype=float),
        method="isotonic",
    )
    frame = meta.copy()
    frame["y"] = y_test.to_numpy(dtype=int)
    frame["p_hgb"] = p_all
    frame["p_logistic"] = p_log
    # Stratify a bit: include some positives if available
    pos = frame[frame["y"] == 1]
    neg = frame[frame["y"] == 0]
    n_pos = min(len(pos), max(5, n // 10))
    n_neg = min(len(neg), n - n_pos)
    sample = pd.concat(
        [
            pos.sample(n=n_pos, random_state=SEED) if n_pos else pos,
            neg.sample(n=n_neg, random_state=SEED) if n_neg else neg,
        ]
    )
    goal = "This job application receives a job offer by the end of the recruiting process"
    feature_cols = [c for c in x_test.columns]
    gpt_ps: list[float] = []
    for idx, row in sample.iterrows():
        # row is meta; get feature vector from x_test aligned by index
        feats_series = x_test.loc[idx]
        feats = {
            c: (None if pd.isna(feats_series[c]) else float(feats_series[c]))
            for c in feature_cols
        }
        feats["checkpoint_type"] = str(row.get("checkpoint_type", ""))
        feats["checkpoint_key"] = str(row.get("checkpoint_key", ""))
        gpt_ps.append(await gpt_probability(provider, model, goal, feats))
    y = sample["y"].astype(int).tolist()
    gpt_s = score(y, gpt_ps)
    pio_s = score(y, sample["p_hgb"].astype(float).tolist())
    log_s = score(y, sample["p_logistic"].astype(float).tolist())
    boot = paired_bootstrap_brier(
        y,
        gpt_ps,
        sample["p_hgb"].astype(float).tolist(),
        [str(i) for i in sample["candidate_id"]],
        seed=SEED,
    )
    return {
        "domain": "career",
        "dataset": "jth_offer_v1",
        "n": len(y),
        "goal": goal,
        "full_test_statistical": metrics,
        "gpt": gpt_s,
        "pio": pio_s,
        "logistic": log_s,
        "relative_brier_reduction_vs_gpt": translate_brier(gpt_s["brier"], pio_s["brier"])["technical"][
            "relative_reduction"
        ],
        "paired_bootstrap_vs_gpt": boot,
        "judge_card": domain_pricing_card(
            "career",
            n=len(y),
            gpt_brier=gpt_s["brier"],
            pio_brier=pio_s["brier"],
            gpt_bins=gpt_s["calibration_bins"],
            pio_bins=pio_s["calibration_bins"],
        ),
        "translations": {
            "brier": translate_brier(gpt_s["brier"], pio_s["brier"]),
            "ece": translate_ece(gpt_s["ece_10"], pio_s["ece_10"]),
            "auc_pio": translate_auc(pio_s["roc_auc"] or 0.5),
            "calibration_pio": translate_calibration_bins(pio_s["calibration_bins"]),
            "calibration_gpt": translate_calibration_bins(gpt_s["calibration_bins"]),
        },
    }


async def main_async(args: argparse.Namespace) -> dict[str, Any]:
    settings = get_settings()
    model = settings.openai_baseline_model
    provider = _provider()
    education = load_education_shared()
    domains: list[dict[str, Any]] = [education]
    if args.skip_live_gpt:
        # statistical-only placeholders for domains without GPT yet
        for name in ("finance", "running", "career"):
            domains.append({"domain": name, "status": "SKIPPED_NO_LIVE_GPT", "reason": "--skip-live-gpt"})
    else:
        if not settings.openai_api_key:
            raise SystemExit("PM_OPENAI_API_KEY required unless --skip-live-gpt")
        domains.append(await eval_shed(provider, model, args.n_per_domain))
        domains.append(await eval_running(provider, model, args.n_per_domain))
        domains.append(await eval_jth(provider, model, args.n_per_domain))

    scored = [d for d in domains if "gpt" in d and "pio" in d and "brier" in d.get("gpt", {})]
    wins = sum(1 for d in scored if d["pio"]["brier"] < d["gpt"]["brier"])
    macro_gpt = float(np.mean([d["gpt"]["brier"] for d in scored])) if scored else None
    macro_pio = float(np.mean([d["pio"]["brier"] for d in scored])) if scored else None
    macro_red = (
        translate_brier(macro_gpt, macro_pio)["technical"]["relative_reduction"]
        if macro_gpt is not None and macro_pio is not None
        else None
    )
    payload = {
        "artifact": "hackathon_proof_v2_pricing",
        "seed": SEED,
        "model_gpt": model,
        "domains": domains,
        "macro": {
            "domains_evaluated": len(scored),
            "domains_won": wins,
            "macro_gpt_brier": macro_gpt,
            "macro_pio_brier": macro_pio,
            "macro_relative_brier_reduction": macro_red,
            "human": (
                f"Play It Out beat GPT in {wins}/{len(scored)} domains and reduced macro "
                f"probability error by {100*macro_red:.1f}%."
                if scored and macro_red is not None
                else None
            ),
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "pricing_results.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-per-domain", type=int, default=50)
    parser.add_argument("--skip-live-gpt", action="store_true")
    args = parser.parse_args()
    payload = asyncio.run(main_async(args))
    print(json.dumps({"macro": payload["macro"], "domains": [d.get("domain") for d in payload["domains"]]}, indent=2))


if __name__ == "__main__":
    main()
