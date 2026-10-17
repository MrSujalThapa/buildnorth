"""Start the API and web demo processes on their documented ports."""

from __future__ import annotations

import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NPM = "npm.cmd" if os.name == "nt" else "npm"


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def expected_service(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return 200 <= response.status < 500
    except OSError:
        return False


def main() -> None:
    api_running = port_open(8000)
    web_running = port_open(5173)
    if api_running and not expected_service("http://127.0.0.1:8000/health"):
        raise SystemExit("Port 8000 is occupied by a process that is not the Play It Out API.")
    if web_running and not expected_service("http://127.0.0.1:5173/"):
        raise SystemExit("Port 5173 is occupied by a process that is not the Play It Out web app.")
    commands: list[list[str]] = []
    if not api_running:
        commands.append([NPM, "run", "dev:api"])
    else:
        print("Reusing healthy API on port 8000.")
    if not web_running:
        commands.append(
            [NPM, "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"]
        )
    else:
        print("Reusing healthy web app on port 5173.")
    if not commands:
        print("Demo stack is already running. Run npm run demo:preflight in another terminal.")
        return
    processes = [subprocess.Popen(command, cwd=ROOT) for command in commands]
    print("Starting API http://127.0.0.1:8000 and web http://127.0.0.1:5173")
    print("Press Ctrl+C to stop both.")
    try:
        while all(process.poll() is None for process in processes):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
    failures = [
        process.returncode for process in processes if process.returncode not in (0, None, -15, 1)
    ]
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
