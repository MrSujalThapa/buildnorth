import asyncio
import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
assert (_REPO_ROOT / "pyproject.toml").exists()
sys.path[:] = [
    entry
    for entry in sys.path
    if "playitout-submission-clean" not in Path(entry or ".").resolve().as_posix()
]

os.environ["PM_ENVIRONMENT"] = "test"
os.environ["PM_COMPOSIO_ENABLED"] = "false"
os.environ.pop("COMPOSIO_API_KEY", None)
os.environ["PM_CORS_ORIGIN_REGEX"] = r"^http://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+):\d+$"

from personal_markets.core.config import get_settings  # noqa: E402
from personal_markets.core.event_loop import configure_windows_selector_event_loop  # noqa: E402

configure_windows_selector_event_loop()
get_settings.cache_clear()


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()

