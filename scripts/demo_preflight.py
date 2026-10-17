"""Read-only readiness check for the recorded demo path; never prints secrets."""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
API = "http://127.0.0.1:8000"
WEB = "http://127.0.0.1:5173"
CAREER = "20000000-0000-0000-0000-000000000002"


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def get_json(url: str) -> object | None:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return None


def environment_names() -> dict[str, str]:
    values = dict(os.environ)
    env_file = ROOT / ".env"
    if env_file.is_file():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            values.setdefault(name.strip(), value.strip())
    return values


def main() -> None:
    failures: list[str] = []
    environment = environment_names()
    required_names = ["PM_DATABASE_URL"]
    missing = [name for name in required_names if not environment.get(name)]
    if missing:
        failures.append(
            f"missing environment names: {', '.join(missing)} (copy .env.example to .env)"
        )

    for path in (
        "benchmarks/hackathon_proof_v2/pricing_results.json",
        "submission/DEMO_RUNBOOK.md",
    ):
        if not (ROOT / path).is_file():
            failures.append(f"missing {path}")

    api_up = port_open(8000)
    web_up = port_open(5173)
    database_url = environment.get("PM_DATABASE_URL")
    if database_url:
        parsed = urlparse(database_url)
        db_port = parsed.port or 5432
        db_host = parsed.hostname or "127.0.0.1"
        with socket.socket() as sock:
            sock.settimeout(1)
            if sock.connect_ex((db_host, db_port)) != 0:
                failures.append(
                    f"Postgres is not reachable at {db_host}:{db_port}; run npm run supabase:start"
                )
    if not api_up:
        failures.append("API is not running on port 8000; run npm run demo:start")
    elif get_json(f"{API}/health") is None:
        failures.append("port 8000 is occupied but the API health endpoint did not respond")
    if not web_up:
        failures.append("web is not running on port 5173; run npm run demo:start")

    if api_up:
        goal = get_json(f"{API}/api/v1/goals/{CAREER}")
        if goal is None:
            failures.append("persisted Career/FDE demo goal is unavailable; run npm run seed-demo")
        state = get_json(f"{API}/api/v1/what-if/baseline-state/{CAREER}")
        if state is None:
            failures.append("What If baseline endpoint did not respond for the Career/FDE goal")
        plugins = get_json(f"{API}/api/v1/plugins")
        if isinstance(plugins, dict):
            github = next(
                (
                    item
                    for item in plugins.get("items", [])
                    if item.get("definition", {}).get("id") == "github"
                ),
                None,
            )
            status = (github or {}).get("connection", {}).get("status")
            if status != "connected":
                failures.append(
                    "GitHub is not connected for the preferred live demo; "
                    "use the persisted offline fallback in submission/DEMO_RUNBOOK.md"
                )
        elif plugins is None:
            failures.append("plugin endpoint did not respond; migrations/startup may be incomplete")

    if failures:
        print("NOT READY:")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)
    print("READY TO RECORD")
    print(f"Markets: {WEB}/")
    print(f"Plugins: {WEB}/plugins")
    print(f"Career goal: {WEB}/goals/{CAREER}")
    print(f"Evidence: {WEB}/goals/{CAREER}/evidence")
    print(f"What If: {WEB}/goals/{CAREER}/what-if")


if __name__ == "__main__":
    main()
