"""Reject new mypy errors while the existing typed-code backlog is repaired."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "scripts" / "mypy_baseline.json"
ERROR = re.compile(r"((?:apps|scripts)[/\\][^:]+):(\d+): error: (.+?)  \[([^]]+)\]")


def findings(from_gh_run: str | None = None) -> Counter[str]:
    command = (
        ["gh", "run", "view", from_gh_run, "--log-failed"]
        if from_gh_run
        else [sys.executable, "-m", "mypy", "--no-error-summary"]
    )
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in ({0} if from_gh_run else {0, 1}):
        raise RuntimeError(result.stderr or result.stdout or "mypy failed")
    counts: Counter[str] = Counter()
    for output in result.stdout.splitlines():
        match = ERROR.search(output)
        if match is None:
            continue
        filename, line_number, message, code = match.groups()
        path = ROOT / filename.replace("\\", "/")
        source = path.read_text(encoding="utf-8").splitlines()
        line = source[int(line_number) - 1].strip()
        key = json.dumps([path.relative_to(ROOT).as_posix(), code, message, line])
        counts[key] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument("--from-gh-run")
    args = parser.parse_args()
    if args.from_gh_run and not args.write_baseline:
        parser.error("--from-gh-run is only for writing a baseline")
    current = findings(args.from_gh_run)
    if args.write_baseline:
        BASELINE.write_text(
            json.dumps(dict(sorted(current.items())), indent=2) + "\n", encoding="utf-8"
        )
        print(f"Recorded {sum(current.values())} existing mypy errors")
        return 0
    baseline = Counter(json.loads(BASELINE.read_text(encoding="utf-8")))
    added = current - baseline
    if added:
        for key, count in sorted(added.items()):
            path, code, message, line = json.loads(key)
            print(f"{path}: {code} {message} ({count}x): {line}")
        print(f"{sum(added.values())} new mypy error(s); strict total {sum(current.values())}")
        return 1
    print(f"No new mypy errors; {sum(current.values())} existing errors remain")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
