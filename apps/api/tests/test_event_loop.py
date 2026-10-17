import asyncio
import sys

from personal_markets.core.event_loop import configure_windows_selector_event_loop


def test_windows_policy_does_not_create_proactor_loops() -> None:
    if sys.platform != "win32":
        return
    configure_windows_selector_event_loop()
    loop = asyncio.new_event_loop()
    try:
        assert "Proactor" not in type(loop).__name__
    finally:
        loop.close()
