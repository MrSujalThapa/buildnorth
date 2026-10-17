"""Verify the committed headline artifact without network access or mutation."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "benchmarks/hackathon_proof_v2/pricing_results.json"
MANIFEST = ROOT / "submission/SUBMISSION_MANIFEST.json"


def main() -> None:
    payload = json.loads(PATH.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for relative, expected_sha in manifest["proof_sha256"].items():
        artifact = ROOT / relative
        actual_sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
        if actual_sha != expected_sha:
            raise SystemExit(
                f"proof artifact checksum mismatch for {relative}: "
                f"expected {expected_sha}, got {actual_sha}"
            )
    macro = payload["macro"]
    expected = {
        "domains_evaluated": 4,
        "domains_won": 3,
        "macro_gpt_brier": 0.13167773124999999,
        "macro_pio_brier": 0.10988608905708233,
        "macro_relative_brier_reduction": 0.16549223612870878,
    }
    for key, value in expected.items():
        actual = macro[key]
        if isinstance(value, float):
            if not math.isclose(actual, value, rel_tol=0, abs_tol=1e-12):
                raise SystemExit(f"{key}: expected {value}, got {actual}")
        elif actual != value:
            raise SystemExit(f"{key}: expected {value}, got {actual}")
    domains = {row["domain"]: row for row in payload["domains"]}
    education = domains["education"]
    if not math.isclose(
        education["relative_brier_reduction_vs_gpt"], 0.2908709237408563, abs_tol=1e-12
    ):
        raise SystemExit("education 29.1% result mismatch")
    wins = sum(row["pio"]["brier"] < row["gpt"]["brier"] for row in domains.values())
    recalculated_gpt = sum(row["gpt"]["brier"] for row in domains.values()) / len(domains)
    recalculated_pio = sum(row["pio"]["brier"] for row in domains.values()) / len(domains)
    if (
        wins != 3
        or not math.isclose(recalculated_gpt, expected["macro_gpt_brier"], abs_tol=1e-12)
        or not math.isclose(recalculated_pio, expected["macro_pio_brier"], abs_tol=1e-12)
    ):
        raise SystemExit("per-domain values do not reproduce the stored macro")
    result = {
        "verified": True,
        "artifact": PATH.relative_to(ROOT).as_posix(),
        "macro": macro,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
