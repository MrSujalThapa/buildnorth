from pathlib import Path
import sys

import personal_markets
import pytest_asyncio

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_pytest_asyncio_loads_from_this_venv() -> None:
    import pytest_asyncio.plugin as plugin

    for module in (pytest_asyncio, plugin):
        path = Path(module.__file__).resolve().as_posix()
        assert "playitout-submission-clean" not in path, path
        assert _REPO_ROOT.resolve().as_posix() in path


def test_product_modules_load_from_this_repository() -> None:
    offenders: list[str] = []
    root = _REPO_ROOT.resolve()
    venv = (root / ".venv").resolve()
    for name, module in sys.modules.items():
        path = getattr(module, "__file__", None)
        if not path:
            continue
        resolved = Path(path).resolve()
        posix = resolved.as_posix()
        if "personal_markets" not in posix and "/apps/api/tests/" not in posix:
            continue
        if posix.startswith(venv.as_posix()):
            continue
        if not posix.startswith(root.as_posix()):
            offenders.append(f"{name}: {resolved}")
    assert offenders == []
    package = Path(personal_markets.__file__).resolve()
    assert str(package).startswith(str(root))
    assert "playitout-submission-clean" not in root.as_posix()


def test_sys_path_does_not_include_sibling_product_repo() -> None:
    for entry in sys.path:
        assert "playitout-submission-clean" not in Path(entry or ".").resolve().as_posix()
