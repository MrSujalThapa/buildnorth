import asyncio
import sys


def configure_windows_selector_event_loop() -> None:
    """psycopg async (LangGraph Postgres checkpointer) cannot use ProactorEventLoop."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
