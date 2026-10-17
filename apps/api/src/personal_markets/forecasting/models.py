from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import logit
from sklearn.base import BaseEstimator
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

CATEGORICAL = ["code_module", "code_presentation"]


def feature_columns(half_life: int) -> list[str]:
    return [
        "code_module",
        "code_presentation",
        "num_of_prev_attempts",
        "studied_credits",
        "module_presentation_length",
        "checkpoint_day",
        "vle_total_clicks",
        "vle_active_days",
        "vle_unique_sites",
        "vle_clicks_7d",
        "vle_clicks_28d",
        f"vle_decayed_clicks_hl{half_life}",
        "vle_days_since_active",
        "vle_click_trend_7d",
        "vle_daily_click_std",
        "assessment_submissions",
        "assessment_mean_score",
        "assessment_score_std",
        "assessment_score_change",
        "assessment_weight_submitted",
        "assessment_weighted_score_sum",
        "assessment_on_time_rate",
        "assessment_days_since_submission",
    ]


def build_model(family: str, columns: list[str]) -> Pipeline:
    numeric = [column for column in columns if column not in CATEGORICAL]
    steps: list[tuple[str, Any]] = [("imputer", SimpleImputer(strategy="median"))]
    if family == "logistic_regression":
        steps.append(("scale", StandardScaler()))
    preprocessor = ColumnTransformer(
        [
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                CATEGORICAL,
            ),
            ("numeric", Pipeline(steps), numeric),
        ]
    )
    if family == "logistic_regression":
        estimator: BaseEstimator = LogisticRegression(max_iter=1000, C=1.0, random_state=20260828)
    elif family == "hist_gradient_boosting":
        estimator = HistGradientBoostingClassifier(
            learning_rate=0.08,
            max_iter=250,
            max_leaf_nodes=31,
            l2_regularization=1.0,
            random_state=20260828,
        )
    else:
        raise ValueError(f"unknown model family: {family}")
    return Pipeline([("preprocessor", preprocessor), ("model", estimator)])


@dataclass(slots=True)
class ProbabilityCalibrator:
    method: str
    model: Any

    @classmethod
    def fit(cls, method: str, raw: np.ndarray, outcomes: np.ndarray) -> "ProbabilityCalibrator":
        logits = logit(np.clip(raw, 1e-6, 1 - 1e-6)).reshape(-1, 1)
        if method == "platt":
            model = LogisticRegression(C=1e6, max_iter=1000).fit(logits, outcomes)
        elif method == "isotonic":
            model = IsotonicRegression(out_of_bounds="clip").fit(raw, outcomes)
        else:
            raise ValueError(f"unknown calibration method: {method}")
        return cls(method, model)

    def predict(self, raw: np.ndarray) -> np.ndarray:
        if self.method == "platt":
            values = self.model.predict_proba(logit(np.clip(raw, 1e-6, 1 - 1e-6)).reshape(-1, 1))[
                :, 1
            ]
        else:
            values = self.model.predict(raw)
        return np.asarray(values, dtype=float)


def split_xy(frame: pd.DataFrame, columns: list[str]) -> tuple[pd.DataFrame, np.ndarray]:
    return frame[columns], frame.outcome.to_numpy(dtype=int)


def logistic_contributions(model: Pipeline, row: pd.DataFrame) -> list[dict[str, float | str]]:
    preprocessor = model.named_steps["preprocessor"]
    estimator = model.named_steps["model"]
    transformed = np.asarray(preprocessor.transform(row))[0]
    coefficients = np.asarray(estimator.coef_)[0]
    names = preprocessor.get_feature_names_out()
    contributions: list[dict[str, float | str]] = [
        {
            "feature": str(name),
            "transformed_value": float(value),
            "coefficient": float(coefficient),
            "log_odds_contribution": float(value * coefficient),
        }
        for name, value, coefficient in zip(names, transformed, coefficients, strict=True)
    ]
    return sorted(
        contributions, key=lambda item: abs(float(item["log_odds_contribution"])), reverse=True
    )
