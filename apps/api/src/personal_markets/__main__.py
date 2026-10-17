"""Windows-safe API entrypoint.

Python 3.14's asyncio.run() ignores event loop policies and creates a Proactor
loop on Windows, which psycopg/LangGraph cannot use. This module starts uvicorn
on a SelectorEventLoop.
"""

from __future__ import annotations

import argparse
import asyncio
import selectors
import sys

import uvicorn

from personal_markets.core.config import get_settings, safe_database_identity
from personal_markets.core.event_loop import configure_windows_selector_event_loop
from personal_markets.main import app


def _selector_loop() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop(selectors.SelectSelector())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    configure_windows_selector_event_loop()
    settings = get_settings()
    identity = (
        safe_database_identity(settings.database_url)
        if settings.database_url and settings.environment not in {"test", "pytest"}
        else "memory"
    )
    print(f"database {identity}", flush=True)
    config = uvicorn.Config(app, host=args.host, port=args.port, log_level="info")
    server = uvicorn.Server(config)
    if sys.platform == "win32":
        asyncio.run(server.serve(), loop_factory=_selector_loop)
        return
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
