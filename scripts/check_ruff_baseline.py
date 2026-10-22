"""Fail on new Ruff findings while retaining visibility into the existing backlog."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "scripts" / "ruff_baseline.json"


def findings() -> Counter[str]:
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", ".", "--output-format=json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in {0, 1}:
        raise RuntimeError(result.stderr or "Ruff failed")
    rows = json.loads(result.stdout)
    counts: Counter[str] = Counter()
    for row in rows:
        path = Path(row["filename"])
        relative = path.relative_to(ROOT).as_posix()
        source = path.read_text(encoding="utf-8").splitlines()
        line = source[row["location"]["row"] - 1].strip()
        key = json.dumps([relative, row["code"], row["message"], line])
        counts[key] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args()
    current = findings()
    if args.write_baseline:
        BASELINE.write_text(
            json.dumps(dict(sorted(current.items())), indent=2) + "\n", encoding="utf-8"
        )
        print(f"Recorded {sum(current.values())} existing Ruff findings")
        return 0
    baseline = Counter(json.loads(BASELINE.read_text(encoding="utf-8")))
    added = current - baseline
    if added:
        for key, count in sorted(added.items()):
            path, code, message, line = json.loads(key)
            print(f"{path}: {code} {message} ({count}x): {line}")
        print(f"{sum(added.values())} new Ruff finding(s); strict total {sum(current.values())}")
        return 1
    print(f"No new Ruff findings; {sum(current.values())} existing findings remain")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
