import asyncio
import selectors
import sys


def configure_windows_selector_event_loop() -> None:
    """psycopg async (LangGraph Postgres checkpointer) cannot use ProactorEventLoop."""
    if sys.platform != "win32":
        return

    class _SelectorEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
        def new_event_loop(self) -> asyncio.AbstractEventLoop:
            return asyncio.SelectorEventLoop(selectors.SelectSelector())

    asyncio.set_event_loop_policy(_SelectorEventLoopPolicy())
