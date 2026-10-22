import json
from datetime import UTC, datetime, timedelta

from personal_markets.evaluation.behavior_eval import run_behavior_evaluation_v2


def test_chronological_validation_is_unaffected_by_test_outcomes(tmp_path) -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    rows = [
        {
            "trial_id": f"{user}-{index}", "user_id": user,
            "domain": "fitness", "action_type": "gym",
            "observed_at": (start + timedelta(days=7 * index)).isoformat(),
            "outcome": float((index + len(user)) % 3 != 0),
        }
        for user in ("consistent", "variable")
        for index in range(25)
    ]
    path = tmp_path / "synthetic.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    first = run_behavior_evaluation_v2(path)
    for row in rows:
        if int(row["trial_id"].split("-")[-1]) >= 20:
            row["outcome"] = 1.0 - row["outcome"]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    second = run_behavior_evaluation_v2(path)
    assert first["selected_recent_half_life_days"] == second["selected_recent_half_life_days"]
    assert first["n_test"] == second["n_test"] == 10
