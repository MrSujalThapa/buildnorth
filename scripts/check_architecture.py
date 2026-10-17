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
            if module.startswith(FORBIDDEN_DOMAIN_PREFIXES) or ".what_if" in module:
                violations.append(f"{relative}: forbidden import {module}")
    if violations:
        print("\n".join(violations))
        return 1
    print("Architecture dependency rules passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
