"""Unit tests for the frozen JTH offer pricing benchmark."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from personal_markets.evaluation.jth_benchmark import (
    FEATURE_COLUMNS,
    build_feature_frame,
    build_feature_matrix,
    create_split_manifest,
    stable_split,
)


def _write_toy_raw(tmp_path: Path) -> Path:
    raw = tmp_path / "raw"
    raw.mkdir()
    pd.DataFrame(
        [
            {
                "candidate_id": "c1",
                "create_date": "2020-01-01",
                "skills": "python;sql",
                "years_experience": "3-6 years",
                "llm_hard_skills": "python",
                "llm_soft_skills": "communication",
                "llm_highest_diploma": "Master",
                "llm_seniority_level": "Mid",
                "llm_management_experience": False,
                "llm_from_top_university": True,
                "llm_number_of_previous_positions": 2,
                "llm_number_of_unique_employers": 2,
            },
            {
                "candidate_id": "c2",
                "create_date": "2020-01-01",
                "skills": "java",
                "years_experience": "0-2 years",
                "llm_hard_skills": "java",
                "llm_soft_skills": "",
                "llm_highest_diploma": "Bachelor",
                "llm_seniority_level": "Junior",
                "llm_management_experience": False,
                "llm_from_top_university": False,
                "llm_number_of_previous_positions": 1,
                "llm_number_of_unique_employers": 1,
            },
        ]
    ).to_csv(raw / "candidates.csv", index=False)
    pd.DataFrame(
        [
            {
                "job_id": "j1",
                "create_date": "2020-01-01",
                "skills": "python",
                "years_experience": "3-6 years",
                "salary": 50000,
                "llm_seniority_level": "Mid",
                "llm_required_lowest_diploma": "Bachelor",
                "llm_required_years_of_work_experience": 3,
                "llm_is_startup": False,
                "llm_is_large_company": True,
                "llm_remote_possible": True,
            }
        ]
    ).to_csv(raw / "jobs.csv", index=False)
    # App A: offer after late interview — early checkpoints must not see interview/offer.
    # App B: no offer; shortlist only.
    pd.DataFrame(
        [
            {
                "application_id": "a1",
                "candidate_id": "c1",
                "job_id": "j1",
                "spontaneous_application_date": "2020-01-01",
                "shortlist_date": "2020-01-10",
                "qualification_date": "",
                "resume_sent_to_company_date": "2020-01-12",
                "1st_interview_date": "2020-02-01",
                "2nd_interview_date": "",
                "3rd_interview_date": "",
                "4th_interview_date": "",
                "job_offer_proposed_date": "2020-02-15",
                "job_offer_accepted_date": "2020-02-20",
                "end_of_process_date": "2020-02-20",
                "last_stage_reached": "Offer Accepted",
                "application_source": "",
            },
            {
                "application_id": "a2",
                "candidate_id": "c2",
                "job_id": "j1",
                "spontaneous_application_date": "2020-01-01",
                "shortlist_date": "2020-01-05",
                "qualification_date": "",
                "resume_sent_to_company_date": "",
                "1st_interview_date": "",
                "2nd_interview_date": "",
                "3rd_interview_date": "",
                "4th_interview_date": "",
                "job_offer_proposed_date": "",
                "job_offer_accepted_date": "",
                "end_of_process_date": "2020-01-20",
                "last_stage_reached": "Shortlist",
                "application_source": "",
            },
        ]
    ).to_csv(raw / "history.csv", index=False)
    return raw


def test_offer_label_definition(tmp_path: Path) -> None:
    raw = _write_toy_raw(tmp_path)
    frame = build_feature_frame(raw)
    by_app = frame.drop_duplicates("application_id").set_index("application_id")["outcome"]
    assert int(by_app.loc["a1"]) == 1
    assert int(by_app.loc["a2"]) == 0


def test_no_future_leakage_on_toy_rows(tmp_path: Path) -> None:
    raw = _write_toy_raw(tmp_path)
    frame = build_feature_frame(raw)
    day0 = frame.loc[
        (frame["application_id"] == "a1") & (frame["checkpoint_key"] == "day_0")
    ].iloc[0]
    assert int(day0["reached_shortlist"]) == 0
    assert int(day0["reached_1st_interview"]) == 0
    assert int(day0["interviews_completed_by_t"]) == 0
    assert int(day0["outcome"]) == 1  # label is final, features are not

    day7 = frame.loc[
        (frame["application_id"] == "a1") & (frame["checkpoint_key"] == "day_7")
    ].iloc[0]
    assert int(day7["reached_shortlist"]) == 0  # shortlist on day 10
    assert int(day7["reached_spontaneous"]) == 1

    after_shortlist = frame.loc[
        (frame["application_id"] == "a1") & (frame["checkpoint_key"] == "after_shortlist")
    ].iloc[0]
    assert int(after_shortlist["reached_shortlist"]) == 1
    assert int(after_shortlist["reached_1st_interview"]) == 0  # interview is later

    after_interview = frame.loc[
        (frame["application_id"] == "a1") & (frame["checkpoint_key"] == "after_1st_interview")
    ].iloc[0]
    assert int(after_interview["reached_1st_interview"]) == 1
    assert int(after_interview["interviews_completed_by_t"]) == 1

    # Offer / accepted dates must never appear as feature columns.
    assert "job_offer_proposed_date" not in frame.columns
    assert "last_stage_reached" not in frame.columns
    assert set(FEATURE_COLUMNS).issubset(set(frame.columns))


def test_split_disjointness(tmp_path: Path) -> None:
    raw = _write_toy_raw(tmp_path)
    manifest = create_split_manifest(raw)
    assert set(manifest["candidate_id"]) == {"c1", "c2"}
    assert manifest["split"].tolist() == [stable_split("c1"), stable_split("c2")]
    assert stable_split("c1") == stable_split("c1")

    frame = build_feature_frame(raw)
    # Same candidate never crosses splits.
    for candidate_id, group in frame.groupby("candidate_id"):
        assert group["split"].nunique() == 1
        assert group["split"].iloc[0] == stable_split(str(candidate_id))

    # Candidate-disjoint across named partitions.
    membership: dict[str, set[str]] = {}
    for split_name in ("train", "val", "cal", "test"):
        part = frame.loc[frame["split"] == split_name, "candidate_id"]
        membership[split_name] = set(part.astype(str))
    splits = list(membership.values())
    for index, left in enumerate(splits):
        for right in splits[index + 1 :]:
            assert left.isdisjoint(right)


def test_build_feature_matrix_columns(tmp_path: Path) -> None:
    raw = _write_toy_raw(tmp_path)
    features = build_feature_frame(raw)
    split_name = features["split"].iloc[0]
    x, y, meta = build_feature_matrix(split_name, features=features)
    assert list(x.columns) == list(FEATURE_COLUMNS)
    assert len(x) == len(y) == len(meta)
    assert set(y.unique()).issubset({0, 1})
