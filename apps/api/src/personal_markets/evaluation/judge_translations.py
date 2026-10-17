"""Judge-facing translations for probabilistic and decision metrics.

Every technical metric has a plain-English companion. Numbers are never invented
here — callers pass measured values.
"""

from __future__ import annotations

from typing import Any


BRIER_ONE_SENTENCE = (
    "Brier measures how close predicted probabilities were to what actually happened; "
    "lower is better and confident wrong predictions are penalized heavily."
)

F1_ONE_SENTENCE = (
    "F1 combines how much real evidence we found with how much of what we extracted "
    "was actually correct."
)


def relative_reduction(baseline: float, improved: float) -> float | None:
    if baseline == 0:
        return None
    return (baseline - improved) / baseline


def pct(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "n/a"
    return f"{100.0 * value:.{digits}f}%"


def pp(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "n/a"
    return f"{100.0 * value:.{digits}f} pp"


def translate_brier(gpt_brier: float, pio_brier: float) -> dict[str, Any]:
    reduction = relative_reduction(gpt_brier, pio_brier)
    return {
        "technical": {"gpt_brier": gpt_brier, "pio_brier": pio_brier, "relative_reduction": reduction},
        "human": {
            "definition": BRIER_ONE_SENTENCE,
            "claim": (
                f"{pct(reduction)} lower probabilistic forecasting error than GPT "
                "on the same resolved forecasts."
                if reduction is not None
                else "Relative Brier reduction undefined (baseline Brier was zero)."
            ),
            "short": f"probability error GPT {gpt_brier:.3f} → PIO {pio_brier:.3f}",
        },
    }


def translate_ece(gpt_ece: float, pio_ece: float) -> dict[str, Any]:
    reduction = relative_reduction(gpt_ece, pio_ece)
    return {
        "technical": {"gpt_ece": gpt_ece, "pio_ece": pio_ece, "relative_reduction": reduction},
        "human": {
            "definition": (
                "When Play It Out says something has roughly a 70% chance, outcomes "
                "predicted around 70% should happen roughly 70% of the time."
            ),
            "claim": (
                "Play It Out’s confidence matches reality more closely "
                f"({pct(reduction)} lower calibration error)."
                if reduction is not None
                else "Calibration comparison unavailable."
            ),
        },
    }


def translate_auc(auc: float) -> dict[str, Any]:
    return {
        "technical": {"auc": auc},
        "human": {
            "definition": (
                "How often does the model correctly rank someone who eventually succeeds "
                "above someone who eventually fails?"
            ),
            "claim": f"Approximately {pct(auc, 0)} pairwise ranking accuracy (AUC={auc:.3f}).",
        },
    }


def translate_calibration_bins(
    bins: list[dict[str, Any]], *, focus_centers: tuple[float, ...] = (0.5, 0.7)
) -> list[dict[str, Any]]:
    """bins items: {lower, upper, count, mean_probability, observed_rate}."""
    out: list[dict[str, Any]] = []
    for center in focus_centers:
        match = None
        for item in bins:
            lower = float(item["lower"])
            upper = float(item["upper"])
            if lower <= center < upper or (center == 1.0 and upper == 1.0):
                match = item
                break
            if abs(((lower + upper) / 2) - center) < 0.051:
                match = item
        if not match or not match.get("count"):
            out.append(
                {
                    "predicted_around": center,
                    "observed_success_rate": None,
                    "count": 0,
                    "human": f"Predicted around {pct(center, 0)}: insufficient cases in bin.",
                }
            )
            continue
        observed = match.get("observed_rate")
        out.append(
            {
                "predicted_around": center,
                "mean_probability": match.get("mean_probability"),
                "observed_success_rate": observed,
                "count": match.get("count"),
                "human": (
                    f"Predicted around {pct(center, 0)} → observed success rate "
                    f"{pct(float(observed) if observed is not None else None, 0)} "
                    f"(n={match.get('count')})."
                ),
            }
        )
    return out


def translate_policy_regret(
    oracle_value: float, pio_value: float, gpt_value: float
) -> dict[str, Any]:
    def capture(value: float) -> float | None:
        if oracle_value == 0:
            return None
        return value / oracle_value

    pio_cap = capture(pio_value)
    gpt_cap = capture(gpt_value)
    return {
        "technical": {
            "oracle_value": oracle_value,
            "pio_value": pio_value,
            "gpt_value": gpt_value,
            "pio_regret": oracle_value - pio_value,
            "gpt_regret": oracle_value - gpt_value,
            "pio_upside_captured": pio_cap,
            "gpt_upside_captured": gpt_cap,
        },
        "human": {
            "definition": "How much upside did the recommendation leave on the table?",
            "claim": (
                f"Play It Out captured {pct(pio_cap, 0)} of available upside versus "
                f"{pct(gpt_cap, 0)} for GPT."
                if pio_cap is not None and gpt_cap is not None
                else "Policy capture undefined."
            ),
        },
    }


def translate_best_action(pio_top1: float, gpt_top1: float) -> dict[str, Any]:
    return {
        "technical": {"pio_top1": pio_top1, "gpt_top1": gpt_top1, "delta_pp": pio_top1 - gpt_top1},
        "human": {
            "claim": (
                "When deciding between several possible actions, Play It Out chose the best one "
                f"{pct(pio_top1, 0)} of the time versus {pct(gpt_top1, 0)} for GPT."
            )
        },
    }


def translate_unsupported_effects(gpt_invent_rate: float, pio_invent_rate: float) -> dict[str, Any]:
    return {
        "technical": {
            "gpt_invented_effect_rate": gpt_invent_rate,
            "pio_invented_effect_rate": pio_invent_rate,
            "delta_pp": gpt_invent_rate - pio_invent_rate,
        },
        "human": {
            "claim": (
                "When evidence was insufficient, GPT invented a numerical effect "
                f"{pct(gpt_invent_rate, 0)} of the time; Play It Out did so "
                f"{pct(pio_invent_rate, 0)}."
            )
        },
    }


def domain_pricing_card(
    domain: str,
    *,
    n: int,
    gpt_brier: float,
    pio_brier: float,
    gpt_bins: list[dict[str, Any]] | None = None,
    pio_bins: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    brier = translate_brier(gpt_brier, pio_brier)
    card: dict[str, Any] = {
        "domain": domain,
        "resolved_cases": n,
        "technical": brier["technical"],
        "human": {
            "probability_error_gpt": gpt_brier,
            "probability_error_pio": pio_brier,
            "accuracy_claim": brier["human"]["claim"],
            "brier_definition": BRIER_ONE_SENTENCE,
        },
    }
    if gpt_bins is not None and pio_bins is not None:
        card["calibration"] = {
            "pio": translate_calibration_bins(pio_bins),
            "gpt": translate_calibration_bins(gpt_bins),
        }
    return card
