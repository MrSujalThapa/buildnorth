"""Generate the audit manifest from committed artifacts and frozen proof inputs."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "submission/SUBMISSION_MANIFEST.json"
PROOF_FILES = [
    "benchmarks/hackathon_proof_v2/pricing_results.json",
    "benchmarks/hackathon_proof_v1/results.json",
    "benchmarks/oulad_completion_v1/benchmark_manifest.json",
    "benchmarks/jth_offer_v1/benchmark_manifest.json",
    "benchmarks/shed_emergency_savings_v1/benchmark_manifest.json",
    "benchmarks/running_volume_2019_v1/benchmark_manifest.json",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    source_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    payload = {
        "project": "Play It Out",
        "branch": "codex/pass-6-end-to-end-product",
        "submission_version": "micro1-final-v1",
        "source_commit": source_commit,
        "source_commit_note": (
            "Commit used as input to this generated manifest; "
            "the packaging commit necessarily follows it."
        ),
        "primary_metric": {
            "name": "macro Brier score on resolved goals",
            "gpt_5_4": 0.13167773124999999,
            "play_it_out": 0.10988608905708233,
            "relative_error_reduction": 0.16549223612870878,
            "domains_won": "3/4",
        },
        "key_artifacts": {
            "judge_start": "submission/README.md",
            "proof": "benchmarks/hackathon_proof_v2/pricing_results.json",
            "proof_table": "benchmarks/hackathon_proof_v2/PROOF_TABLE.md",
            "reproduction": "docs/REPRODUCTION.md",
            "changelog": "docs/IMPROVEMENT_CHANGELOG.md",
            "trajectory_index": "submission/trajectories/index.json",
            "demo_runbook": "submission/DEMO_RUNBOOK.md",
        },
        "agents": [
            "Goal Architect",
            "Source Planner",
            "Evidence Agent",
            "Research Agent",
            "Intervention Agent",
            "Forecast Critic",
        ],
        "trajectory_count": 12,
        "dataset_manifests": [
            path for path in PROOF_FILES if path.endswith("benchmark_manifest.json")
        ],
        "proof_sha256": {path: sha256(ROOT / path) for path in PROOF_FILES},
        "commands": {
            "submission_verify": "npm run verify:submission",
            "demo_preflight": "npm run demo:preflight",
            "demo_start": "npm run demo:start",
            "frozen_proof": "uv run python scripts/verify_frozen_proof.py",
            "optional_live_e2e": "npm run test:e2e:live",
        },
        "tests": {
            "backend": "184 passed, 4 skipped at baseline; rerun by verify:submission",
            "frontend": "21 passed at baseline; rerun by verify:submission",
            "typescript": "shipped web application check included",
            "playwright_submission": (
                "foundation + resource/evidence/behavior/What If deterministic suite"
            ),
            "repository_wide_python_static_analysis": (
                "known historical Ruff/mypy debt; scoped submission Python is gated"
            ),
        },
        "known_limitations": [
            "Live GPT regeneration requires OpenAI quota; frozen verification does not.",
            "Raw licensed datasets require documented acquisition and are not redistributed.",
            "Five traces contain provider tool envelopes; missing telemetry remains null.",
            "Action-policy measurements are simulator/model-consistent, "
            "not causal treatment effects.",
        ],
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
