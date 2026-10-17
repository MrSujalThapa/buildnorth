from personal_markets.evaluation.agent_eval import run_agent_evaluation


def test_agent_eval_suite_is_deterministic() -> None:
    first = run_agent_evaluation()
    second = run_agent_evaluation()
    assert first == second
    assert first["goal_architect"]["n"] >= 40
    assert first["evidence_agent"]["n"] >= 30
    assert first["critic"]["n"] >= 15
    assert first["critic"]["false_veto"] == 0
    assert first["critic"]["decision_matches"] == first["critic"]["n"]
    assert first["goal_architect"]["necessary_clarification_missed"] == 0
    assert first["evidence_agent"]["event_count_matches"] == first["evidence_agent"]["n"]
    assert first["case_counts"]["frozen_interventions"] >= 30
    assert first["case_counts"]["frozen_source_planner"] >= 20
    assert first["case_counts"]["frozen_source_planner_resource_level"] >= 12
    assert first["source_planner_resources"]["n"] >= 12
    assert first["source_planner_resources"]["resource_level_n"] >= 12
    # Scripted ranking sanity only — not live GPT numbers.
    assert first["source_planner_resources"]["top1"] >= 0.5
    assert first["source_planner_resources"]["ndcg_at_k"] >= 0.5
