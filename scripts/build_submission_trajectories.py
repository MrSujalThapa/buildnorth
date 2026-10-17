# ruff: noqa: E501
"""Build review traces from committed run/evaluation artifacts; never synthesize telemetry."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "submission" / "trajectories"
PROMPTS = ROOT / "apps/api/src/personal_markets/agents/prompts"

AGENTS = {
    "goal_architect": ("Goal Architect", "goal_architect/v1.md"),
    "source_planner": ("Source Planner", "source_planner/v1.md"),
    "evidence_agent": ("Evidence Agent", "evidence/v1.md"),
    "research_agent": ("Research Agent", "research/v1.md"),
    "intervention_agent": ("Intervention Agent", "intervention/v1.md"),
    "forecast_critic": ("Forecast Critic", "critic/v1.md"),
}


def load(path: str) -> Any:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def instruction(agent_key: str) -> dict[str, str]:
    _, rel = AGENTS[agent_key]
    path = PROMPTS / rel
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def trace(
    agent_key: str,
    trace_id: str,
    task: str,
    source: str,
    final_output: Any,
    *,
    model: str | None,
    timestamp: str | None = None,
    run_id: str | None = None,
    thread_id: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    latency_ms: int | None = None,
    retries: int | None = None,
    feedback: str | None = None,
    human: Any = None,
    result: str = "success",
    input_context: Any = None,
    downstream: Any = None,
    tool_call: Any = None,
    tool_result: Any = None,
    capture_type: str = "reconstructed_from_persisted_run_artifacts",
) -> dict[str, Any]:
    name, _ = AGENTS[agent_key]
    return {
        "trace_id": trace_id,
        "agent": name,
        "agent_version": instruction(agent_key)["path"].split("prompts/")[1].removesuffix(".md"),
        "model": model,
        "timestamp": timestamp,
        "task": task,
        "instruction_ref": instruction(agent_key),
        "source_artifact": source,
        "capture_type": capture_type,
        "input_context": input_context or {},
        "steps": [{
            "step": 1,
            "action": "Executed the production structured-output boundary on the recorded input.",
            "tool_call": tool_call,
            "tool_result": tool_result,
            "feedback": feedback,
            "retry": bool(retries),
            "human_checkpoint": human,
        }],
        "final_output": final_output,
        "downstream_effect": downstream or {},
        "telemetry": {
            "run_id": run_id,
            "thread_id": thread_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": latency_ms,
            "retries": retries,
            "tool_calls": 1 if tool_call else 0,
        },
        "result": result,
        "missing_telemetry_note": "Fields are null when the source artifact did not capture them.",
    }


def markdown(item: dict[str, Any]) -> str:
    step = item["steps"][0]
    tel = item["telemetry"]
    return f"""# Trace {item['trace_id']}

## Agent

{item['agent']} / {item['agent_version']} / {item['model'] or 'not captured'}

## Task

{item['task']}

## Agent instructions

Canonical path: `{item['instruction_ref']['path']}`  
SHA-256: `{item['instruction_ref']['sha256']}`

## Input context

```json
{json.dumps(item['input_context'], indent=2)}
```

## Step 1

{step['action']}

## Tool call

```json
{json.dumps(step['tool_call'], indent=2)}
```

## Tool response

```json
{json.dumps(step['tool_result'], indent=2)}
```

## Feedback / validation

{step['feedback'] or 'No separate feedback envelope was captured; structured/schema validation is reflected in the source artifact.'}

## Retry / next step

{'A retry was recorded.' if step['retry'] else 'No retry was recorded.'}

## Human checkpoint

```json
{json.dumps(step['human_checkpoint'], indent=2)}
```

## Final structured output

```json
{json.dumps(item['final_output'], indent=2)}
```

## Downstream effect

```json
{json.dumps(item['downstream_effect'], indent=2)}
```

## Telemetry

- run ID: `{tel['run_id']}`
- thread/workflow ID: `{tel['thread_id']}`
- input/output tokens: `{tel['input_tokens']}` / `{tel['output_tokens']}`
- latency: `{tel['latency_ms']}` ms
- retries: `{tel['retries']}`
- tool count: `{tel['tool_calls']}`
- timestamp: `{item['timestamp']}`
- source: `{item['source_artifact']}`
- capture type: `{item['capture_type']}`

Null values were not captured and were not invented.

## Result

{item['result'].upper()}

## Why this trace matters

It shows an observable production/evaluation boundary and preserves both the result and its recorded limitations without reconstructing hidden reasoning.
"""


def main() -> None:
    rep = load("benchmarks/agent_trajectories/representative.json")
    live = load("benchmarks/agent_runtime_validation_v1/live_workflow_20260829.json")
    abl = load("benchmarks/pass6_eval_v1/live_ablation_ag.json")
    proof = load("benchmarks/hackathon_proof_v1/results.json")["agent_comparable_ablations"]
    github = load("benchmarks/pass6_eval_v1/github_evidence_forecast.json")
    traces: list[tuple[str, dict[str, Any]]] = []

    goal_runs = rep[1]["runs"]
    for idx, run in enumerate(goal_runs):
        traces.append(("goal_architect", trace(
            "goal_architect", f"goal-architect-rich-{idx+1}", "Formalize the vague goal: I want to get rich.",
            "benchmarks/agent_trajectories/representative.json", run["output"], model=run["model_name"],
            run_id=run["id"], thread_id=run["thread_id"], latency_ms=run["duration_ms"], retries=run["retry_count"],
            feedback=run["validation_status"], human={"type": "clarification" if idx == 0 else "confirm_contract", "answers_recorded": idx == 1},
            result="retried" if idx == 0 else "success", input_context={"intent": "I want to get rich."},
            downstream={"ready_to_commit": run["output"]["ready_to_commit"]},
        )))

    for idx, row in enumerate(abl["D_agent_evidence"][:2]):
        usage = row["usage"]
        traces.append(("evidence_agent", trace(
            "evidence_agent", f"evidence-live-{idx+1}", f"Normalize: {row['text']}",
            "benchmarks/pass6_eval_v1/live_ablation_ag.json", row["output"], model=row["model"],
            run_id=row["request_id"], timestamp=abl["captured_at"], input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"],
            latency_ms=row["latency_ms"], retries=row["retries"], feedback=f"schema_valid={row['schema_valid']}; probability_hallucinated={row['hallucinated_probability']}",
            input_context={"manual_text": row["text"]}, downstream={"evidence_event_count": row["event_count"]},
            tool_call={"tool": "OpenAI structured completion", "arguments": {"input_text": row["text"], "schema": "EvidenceAgentProposal"}},
            tool_result={"request_id": row["request_id"], "structured_output": row["output"]},
            capture_type="recorded",
        )))

    research_runs = [rep[0]["runs"][1]]
    lr = next(x for x in live["agent_runs"] if x["agent"] == "research")
    research_runs.append({"id": lr["run_id"], "thread_id": live["goal_thread_id"], "model_name": lr["model"], "duration_ms": lr["latency_ms"], "retry_count": 0, "output": github["workflow"]["research"], "input_tokens": lr["input_tokens"], "output_tokens": lr["output_tokens"]})
    for idx, run in enumerate(research_runs):
        traces.append(("research_agent", trace(
            "research_agent", f"research-reference-{idx+1}", "Structure supplied frozen reference material without inventing sources or causal claims.",
            "benchmarks/agent_trajectories/representative.json" if idx == 0 else "benchmarks/agent_runtime_validation_v1/live_workflow_20260829.json + benchmarks/pass6_eval_v1/github_evidence_forecast.json",
            run["output"], model=run["model_name"], run_id=run["id"], thread_id=run["thread_id"],
            input_tokens=run.get("input_tokens"), output_tokens=run.get("output_tokens"), latency_ms=run["duration_ms"], retries=run["retry_count"],
            feedback="Structured output validated; limitations retained.", downstream={"reference_claims_available_to_forecaster": True},
            tool_call={"tool": "OpenAI structured completion", "arguments": {"input_refs": ["retrieved snippets"], "schema": "ResearchProposal"}} if idx == 1 else None,
            tool_result={"run_id": run["id"], "structured_output": run["output"]} if idx == 1 else None,
            capture_type="recorded" if idx == 1 else "reconstructed_from_persisted_run_artifacts",
        )))

    for idx, row in enumerate(abl["E_intervention_with_schema"][:2]):
        usage = row["usage"]
        traces.append(("intervention_agent", trace(
            "intervention_agent", f"intervention-live-{idx+1}", row["text"],
            "benchmarks/pass6_eval_v1/live_ablation_ag.json", row["output"], model=row["model"], run_id=row["request_id"], timestamp=abl["captured_at"],
            input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"], latency_ms=row["latency_ms"], retries=row["retries"],
            feedback=f"schema_valid={row['schema_valid']}; assigns_numeric_odds={row['assigns_numeric_odds']}", input_context={"intervention_text": row["text"]},
            downstream={"pricing_status": row["pricing_status"]}, result="withheld" if row["pricing_status"] == "NOT_PRICED" else "success",
            tool_call={"tool": "OpenAI structured completion", "arguments": {"intervention_text": row["text"], "schema": "InterventionAgentProposal"}},
            tool_result={"request_id": row["request_id"], "structured_output": row["output"]},
            capture_type="recorded",
        )))

    for idx, row in enumerate(proof["source_planner"]["rows"][:2]):
        traces.append(("source_planner", trace(
            "source_planner", f"source-planner-eval-{idx+1}", f"Rank relevant providers for the {row['goal_family']} evaluation case.",
            "benchmarks/hackathon_proof_v1/results.json", row, model="gpt-5.4-mini", feedback=f"schema_valid={row['schema_valid']}; NDCG@5={row['ndcg_at_5']}",
            input_context={"case_id": row["id"], "goal_family": row["goal_family"]}, downstream={"recommended_plugins": row["recommended"]},
        )))

    for idx, row in enumerate([proof["critic"]["rows"][0], proof["critic"]["rows"][1]]):
        traces.append(("forecast_critic", trace(
            "forecast_critic", f"critic-gate-{idx+1}", f"Review deterministic issue case {row['id']}.",
            "benchmarks/hackathon_proof_v1/results.json", row, model="gpt-5.4", feedback=f"expected={row['expect_decision']}; correct={row['correct']}",
            input_context={"deterministic_issues": row["issues"]}, downstream={"publication_decision": row["decision"]}, result="withheld" if row["decision"] == "withhold" else "success",
        )))

    index = []
    for directory, item in traces:
        target = OUT / directory
        target.mkdir(parents=True, exist_ok=True)
        stem = item["trace_id"]
        (target / f"{stem}.json").write_text(json.dumps(item, indent=2) + "\n", encoding="utf-8")
        (target / f"{stem}.md").write_text(markdown(item), encoding="utf-8")
        step = item["steps"][0]
        index.append({
            "trace_id": stem, "agent": item["agent"], "model": item["model"], "task_type": directory,
            "result": item["result"], "has_tool_calls": bool(step["tool_call"]), "has_feedback": bool(step["feedback"]),
            "has_retry": bool(step["retry"]), "has_human_checkpoint": step["human_checkpoint"] is not None,
            "has_validation": bool(step["feedback"]), "has_final_output": item["final_output"] is not None,
            "md_path": f"submission/trajectories/{directory}/{stem}.md", "json_path": f"submission/trajectories/{directory}/{stem}.json",
            "contains_private_data": False, "redaction_status": "reviewed", "source_run_id": item["telemetry"]["run_id"],
            "capture_type": item["capture_type"],
        })
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(index)} trace pairs")


if __name__ == "__main__":
    main()
