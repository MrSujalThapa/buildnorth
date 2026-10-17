import shutil
from pathlib import Path

import pytest

from personal_markets.evaluation.oulad import OuladDatasetAdapter
from personal_markets.evaluation.oulad_benchmark import build_feature_frame, stable_split


def test_oulad_fixture_matches_required_schema() -> None:
    fixture = Path(__file__).parent / "fixtures" / "oulad"
    OuladDatasetAdapter().validate_directory(fixture)


def test_oulad_adapter_rejects_incomplete_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="missing"):
        OuladDatasetAdapter().validate_directory(tmp_path)


def test_future_events_cannot_enter_past_checkpoint(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "oulad"
    for source in fixture.glob("*.csv"):
        shutil.copy(source, tmp_path / source.name)
    with (tmp_path / "studentVle.csv").open("a", encoding="utf-8") as handle:
        handle.write("AAA,2013J,1,1,200,9999\n")
    frame = build_feature_frame(tmp_path)
    assert set(frame.vle_total_clicks) == {4}


def test_group_split_is_deterministic() -> None:
    assert stable_split(12345) == stable_split(12345)
