import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

BASELINE_RECEIPT_KEYS = (
    "receipt_version",
    "forecast_kind",
    "goal_id",
    "goal_contract_version",
    "state_snapshot_id",
    "state_snapshot_version",
    "evidence_watermark",
    "normalized_evidence_ids",
    "feature_transforms",
    "model",
    "reference_versions",
    "raw_probability",
    "calibrated_probability",
    "final_probability",
    "calibration",
    "forecast_status",
    "assumptions",
    "limitations",
    "critic_decision",
    "agent_run_ids",
    "run_id",
    "llm_used_for_probability",
)

SIMULATION_RECEIPT_KEYS = (
    "receipt_version",
    "run_kind",
    "goal_id",
    "seed",
    "model",
    "assumptions",
    "llm_used",
    "critic_decision",
)

IMPACT_RECEIPT_KEYS = (
    *SIMULATION_RECEIPT_KEYS,
    "draws",
    "convergence",
    "intervention",
    "execution_probability",
    "raw_probability",
    "final_expected_probability",
)


def missing_receipt_keys(receipt: dict[str, Any], required: tuple[str, ...]) -> list[str]:
    return [key for key in required if key not in receipt]


class ForecastReceiptRepresentation(BaseModel):
    receipt: dict[str, Any]
    summary: str


class ForecastReceipt(BaseModel):
    receipt_version: int = 1
    forecast_id: str
    goal_id: str
    goal_contract_version: int = Field(ge=1)
    case_id: str
    as_of_day: int = Field(ge=0)
    evidence_watermark: str
    relevant_evidence_ids: list[str]
    state_snapshot_id: str
    state_snapshot_version: int = Field(ge=1)
    run_id: str
    raw_probability: float = Field(ge=0, le=1)
    calibrated_probability: float = Field(ge=0, le=1)
    forecast_status: str
    model: dict[str, Any]
    calibration: dict[str, Any]
    feature_schema_version: str
    feature_snapshot: dict[str, Any]
    transformations: dict[str, Any]
    training_dataset: dict[str, Any]
    assumptions: list[str]
    contributions: list[dict[str, Any]]
    provenance: dict[str, Any]
    limitations: list[str]
    critic_decision: str | None = None
    goal_architect_run_id: str | None = None
    evidence_agent_run_ids: list[str] = Field(default_factory=list)
    research_agent_run_ids: list[str] = Field(default_factory=list)
    critic_run_id: str | None = None
    research_source_ids: list[str] = Field(default_factory=list)
    normalized_evidence_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def content_hash(self) -> str:
        payload = self.model_dump(mode="json", exclude={"created_at"})
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def human_summary(self) -> str:
        probability = round(self.calibrated_probability * 100, 1)
        return (
            f"{probability}% estimated completion probability as of day {self.as_of_day} "
            f"({self.forecast_status}; {self.model.get('family', 'unknown')} model)."
        )

    def api_representation(self) -> ForecastReceiptRepresentation:
        return ForecastReceiptRepresentation(
            receipt=self.model_dump(mode="json"), summary=self.human_summary()
        )
