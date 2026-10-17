"""Offline submission artifact, link, path, secret, and fixture-boundary checks."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "README.md",
    "docs/IMPROVEMENT_CHANGELOG.md",
    "docs/REPRODUCTION.md",
    "benchmarks/hackathon_proof_v2/pricing_results.json",
    "benchmarks/hackathon_proof_v2/PROOF_TABLE.md",
    "benchmarks/hackathon_proof_v2/JUDGE_SUMMARY.md",
    "submission/README.md",
    "submission/SUBMISSION_CHECKLIST.md",
    "submission/SUBMISSION_MANIFEST.json",
    "submission/AGENT_INSTRUCTIONS_INDEX.md",
    "submission/AGENT_TRAJECTORIES.md",
    "submission/TRAJECTORY_REIMBURSEMENT_README.md",
    "submission/REDACTION_REPORT.md",
    "submission/REPRO_VERIFICATION.md",
    "submission/RUBRIC_MAPPING.md",
    "submission/FAILURE_MODE_AND_HOT_TAKE.md",
    "submission/DEMO_RUNBOOK.md",
    "submission/TOMORROW_VIDEO_CHECKLIST.md",
    "submission/trajectories/index.json",
]
TEXT_SUFFIXES = {".md", ".json", ".py", ".ts", ".tsx", ".js", ".yml", ".yaml"}
LOCAL_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/](?:Users|Documents)|Users[\\/]sujal|vscode-file://|file://)", re.I
)
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}", re.I),
    re.compile(r"(?:OPENAI|COMPOSIO|SUPABASE)[A-Z_]*KEY\s*[=:]\s*['\"]?[A-Za-z0-9_-]{12,}", re.I),
]
LINK = re.compile(r"\[[^\]]+\]\((?!https?://|mailto:|#)([^)]+)\)")
FORBIDDEN_BUILDERS = {"buildCompareSimulations", "buildFutureSimulations", "pathsForFrontier"}


def tracked_files() -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        text=True,
    )
    return [ROOT / line for line in output.splitlines() if line]


def main() -> None:
    errors: list[str] = []
    for item in REQUIRED:
        if not (ROOT / item).is_file():
            errors.append(f"missing required artifact: {item}")

    index_path = ROOT / "submission/trajectories/index.json"
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        agents = {row["agent"] for row in index}
        if len(index) != 12 or len(agents) != 6:
            errors.append(
                f"trajectory coverage expected 12 traces/6 agents, got {len(index)}/{len(agents)}"
            )
        for row in index:
            for key in ("md_path", "json_path"):
                if not (ROOT / row[key]).is_file():
                    errors.append(f"missing trajectory file: {row[key]}")

    for path in tracked_files():
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(ROOT).as_posix()
        if (
            rel.startswith(("submission/", "docs/", "benchmarks/hackathon_proof_v2/"))
            or rel == "README.md"
        ):
            if LOCAL_PATH.search(text):
                errors.append(f"absolute/local path in submission-facing file: {rel}")
            if path.suffix.lower() == ".md":
                for match in LINK.finditer(text):
                    target = match.group(1).strip("<>").split("#", 1)[0]
                    if target and not (path.parent / target).resolve().exists():
                        errors.append(f"broken link: {rel} -> {target}")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                errors.append(f"possible secret ({pattern.pattern}) in {rel}")

    production = ROOT / "apps/web/src"
    for path in production.rglob("*.tsx"):
        text = path.read_text(encoding="utf-8")
        used = sorted(name for name in FORBIDDEN_BUILDERS if re.search(rf"\b{name}\b", text))
        if used:
            errors.append(
                f"production fixture builder import/use in {path.relative_to(ROOT)}: {used}"
            )

    if errors:
        print("SUBMISSION ARTIFACT CHECK FAILED")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print("submission files: PASS")
    print("links and local paths: PASS")
    print("secret patterns: PASS")
    print("production What If fixture-builder boundary: PASS")


if __name__ == "__main__":
    main()
