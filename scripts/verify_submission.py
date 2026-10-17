"""Run the offline, deterministic submission gate and report every result."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IS_WINDOWS = os.name == "nt"
NPM = "npm.cmd" if IS_WINDOWS else "npm"

GATES = [
    ("frozen proof", ["uv", "run", "python", "scripts/verify_frozen_proof.py"]),
    ("proof assembly", ["uv", "run", "python", "scripts/assemble_hackathon_proof_v2.py"]),
    ("backend", ["uv", "run", "pytest"]),
    ("frontend tests", [NPM, "run", "test", "--workspace", "@personal-markets/web"]),
    ("frontend TypeScript", [NPM, "run", "typecheck", "--workspace", "@personal-markets/web"]),
    (
        "changed Python",
        [
            "uv",
            "run",
            "ruff",
            "check",
            "scripts/check_submission_artifacts.py",
            "scripts/verify_frozen_proof.py",
            "scripts/verify_submission.py",
            "scripts/demo_preflight.py",
            "scripts/demo_start.py",
            "scripts/build_submission_trajectories.py",
            "scripts/build_submission_manifest.py",
        ],
    ),
    ("build", [NPM, "run", "build"]),
    ("E2E", [NPM, "run", "test:e2e:submission"]),
    (
        "submission files / links / secrets",
        ["uv", "run", "python", "scripts/check_submission_artifacts.py"],
    ),
    ("diff whitespace", ["git", "diff", "--check"]),
    (
        "clean artifacts",
        [
            "git",
            "diff",
            "--exit-code",
            "--",
            "benchmarks/hackathon_proof_v2",
            "submission/trajectories",
        ],
    ),
]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    results: list[tuple[str, bool]] = []
    for name, command in GATES:
        print(f"\n=== {name}: {' '.join(command)} ===", flush=True)
        completed = subprocess.run(command, cwd=ROOT, check=False)
        results.append((name, completed.returncode == 0))
        if completed.returncode:
            break

    print("\nSUBMISSION VERIFY")
    for name, passed in results:
        print(f"{'✓' if passed else '✗'} {name}")
    not_run = [name for name, _ in GATES[len(results) :]]
    for name in not_run:
        print(f"- {name} (not run)")
    if not all(passed for _, passed in results) or len(results) != len(GATES):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
