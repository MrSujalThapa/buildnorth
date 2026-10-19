import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "apps" / "api" / "src" / "personal_markets"
FORBIDDEN_DOMAIN_PREFIXES = ("openai", "langgraph", "monid", "fastapi", "react")
CORE_AREAS = {"core", "goals", "evidence", "state", "forecasting", "simulation", "optimization"}
DOMAIN_FILENAMES = {"domain.py", "events.py", "repository.py", "service.py"}


def main() -> int:
    violations: list[str] = []
    for path in ROOT.rglob("*.py"):
        relative = path.relative_to(ROOT)
        if relative.parts[0] not in CORE_AREAS or path.name not in DOMAIN_FILENAMES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        for module in imported:
            if (
                module.startswith(FORBIDDEN_DOMAIN_PREFIXES)
                or module.startswith("mcp")
                or ".what_if" in module
                or ".remote_mcp" in module
            ):
                violations.append(f"{relative}: forbidden import {module}")
    route_files = [
        ROOT / "main.py",
        ROOT / "wiring.py",
        *ROOT.rglob("*api.py"),
        *ROOT.rglob("*router.py"),
        *ROOT.rglob("remote_mcp/*.py"),
    ]
    forbidden_eval = (
        "evaluate_openai_baseline",
        "eval_hackathon_proof",
        "eval_pass6_live_ablation",
        "scripts.evaluate",
        "personal_markets.evaluation",
    )
    seen: set[Path] = set()
    for path in route_files:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        text = path.read_text(encoding="utf-8")
        for token in forbidden_eval:
            if token in text:
                relative = path.relative_to(ROOT)
                violations.append(f"{relative}: deployed route must not reference {token}")
    if violations:
        print("\n".join(violations))
        return 1
    print("Architecture dependency rules passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
