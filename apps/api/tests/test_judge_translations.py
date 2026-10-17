"""Unit tests for judge-facing metric translations."""

from personal_markets.evaluation.judge_translations import (
    translate_auc,
    translate_brier,
    translate_unsupported_effects,
)


def test_translate_brier_oulad_style() -> None:
    out = translate_brier(0.222799, 0.157994)
    assert out["technical"]["relative_reduction"] is not None
    assert abs(out["technical"]["relative_reduction"] - 0.29087) < 1e-3
    assert "29" in out["human"]["claim"]
    assert "lower probabilistic forecasting error" in out["human"]["claim"]


def test_translate_auc() -> None:
    out = translate_auc(0.861)
    assert "86%" in out["human"]["claim"] or "86.1%" in out["human"]["claim"]


def test_unsupported_effects() -> None:
    out = translate_unsupported_effects(1.0, 0.14)
    assert "100%" in out["human"]["claim"]
    assert "14%" in out["human"]["claim"]
