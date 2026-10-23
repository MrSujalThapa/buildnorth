import pytest
from fastapi.testclient import TestClient

from helpers import isolated_app
from personal_markets.core.errors import SemanticProviderError
from personal_markets.forecasting.course_grade import (
    CourseGradeRequest,
    GradeComponent,
    evaluate_course_grade,
)
from personal_markets.remote_mcp.weighted import WeightedScoreRequest, compute_weighted_score


def _syllabus(
    *, final_score: float | None = None, final_known: bool = False
) -> list[GradeComponent]:
    return [
        GradeComponent(label="midterm", score=90, weight=30),
        GradeComponent(label="final", score=final_score, weight=70, known=final_known),
    ]


def test_current_standing_and_required_final_are_exact_arithmetic() -> None:
    result = evaluate_course_grade(CourseGradeRequest(components=_syllabus(), target=70))
    assert result.status == "needs_scores"
    assert result.writes_evidence is False
    assert result.arithmetic_only is True
    assert result.known_contribution == pytest.approx(27.0)
    assert result.required_remaining == pytest.approx(61.428571, rel=1e-6)
    assert result.average is None
    assert "final" in " ".join(result.missing)


def test_exam_50_versus_80_are_side_by_side_and_not_evidence() -> None:
    result = evaluate_course_grade(
        CourseGradeRequest(components=_syllabus(), target=70, scenarios=[50, 80])
    )
    by_score = {item.remaining_score: item for item in result.scenarios}
    assert by_score[50].average == pytest.approx(62.0)
    assert by_score[50].meets_target is False
    assert by_score[80].average == pytest.approx(83.0)
    assert by_score[80].meets_target is True
    assert result.writes_evidence is False


def test_completed_syllabus_is_not_an_unweighted_mean() -> None:
    result = evaluate_course_grade(
        CourseGradeRequest(components=_syllabus(final_score=80, final_known=True), target=70)
    )
    assert result.status == "computed"
    assert result.average == pytest.approx(83.0)
    assert result.average != pytest.approx(85.0)


def test_two_unknowns_leave_required_mark_uniform_and_name_the_gap() -> None:
    result = evaluate_course_grade(
        CourseGradeRequest(
            components=[
                GradeComponent(label="labs", score=100, weight=20),
                GradeComponent(label="midterm", score=None, weight=30, known=False),
                GradeComponent(label="final", score=None, weight=50, known=False),
            ],
            target=80,
        )
    )
    assert result.status == "needs_scores"
    assert result.required_is_uniform is True
    assert result.required_remaining == pytest.approx(75.0)
    assert "midterm" in result.missing
    assert "final" in result.missing


def test_target_already_met_and_unattainable_are_explicit() -> None:
    met = evaluate_course_grade(
        CourseGradeRequest(components=_syllabus(final_score=80, final_known=True), target=70)
    )
    assert met.already_met is True
    assert met.unattainable is False
    unreachable = evaluate_course_grade(
        CourseGradeRequest(components=_syllabus(), target=99)
    )
    assert unreachable.unattainable is True
    assert unreachable.required_remaining == pytest.approx(102.85714, rel=1e-5)


def test_weights_that_do_not_sum_are_rejected() -> None:
    with pytest.raises(SemanticProviderError, match="sum"):
        evaluate_course_grade(
            CourseGradeRequest(
                components=[
                    GradeComponent(label="midterm", score=90, weight=30),
                    GradeComponent(label="final", score=80, weight=30),
                ]
            )
        )


def test_hypothetical_scores_stay_within_course_scale() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CourseGradeRequest(components=_syllabus(), scenarios=[101])
    with pytest.raises(ValidationError):
        CourseGradeRequest(components=_syllabus(), scenarios=[-1])


def test_mcp_wrapper_keeps_needs_clarification_and_71_average() -> None:
    waiting = compute_weighted_score(
        WeightedScoreRequest(
            components=[
                GradeComponent(label="midterm", score=90, weight=30),
                GradeComponent(label="final", score=None, weight=70, known=False),
            ]
        )
    )
    assert waiting.status == "needs_clarification"
    assert waiting.average is None
    done = compute_weighted_score(
        WeightedScoreRequest(
            components=[
                GradeComponent(label="midterm", score=50, weight=0.3),
                GradeComponent(label="final", score=80, weight=0.7),
            ]
        )
    )
    assert done.status == "computed"
    assert done.average == 71.0


def test_course_grade_http_is_invited_arithmetic_only() -> None:
    app = isolated_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/what-if/course-grade",
            json={
                "components": [
                    {"label": "midterm", "score": 90, "weight": 30},
                    {"label": "final", "score": None, "weight": 70, "known": False},
                ],
                "target": 70,
                "scenarios": [50, 80],
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["writes_evidence"] is False
    assert body["arithmetic_only"] is True
    assert body["required_remaining"] == pytest.approx(61.428571, rel=1e-6)
    scenario_averages = {row["remaining_score"]: row["average"] for row in body["scenarios"]}
    assert scenario_averages[50] == pytest.approx(
        62.0
    )
