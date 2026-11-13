"""Guards for the dependency layout: runtime vs dev requirements and the hashed Modal lock."""

from __future__ import annotations

import re
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
RUNTIME = API_ROOT / "requirements.txt"
DEV = API_ROOT / "requirements-dev.txt"
LOCK = API_ROOT / "requirements.lock"

DEV_ONLY = {"pytest", "pytest-asyncio", "pandas", "pyarrow", "modal", "pglast", "ruff", "pip-audit"}
# Only needed on Python < 3.10, which the Python 3.11 lock does not cover.
OLD_PYTHON_ONLY = {"eval-type-backport"}


def _normalize(name: str) -> str:
    return name.lower().replace("_", "-")


def _requirement_names(path: Path) -> set[str]:
    names: set[str] = set()
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        match = re.match(r"^([A-Za-z0-9_.\-]+)", line)
        if match:
            names.add(_normalize(match.group(1)))
    return names


def test_runtime_requirements_exclude_dev_only_packages():
    assert not (_requirement_names(RUNTIME) & DEV_ONLY)


def test_dev_requirements_extend_runtime_requirements():
    assert "-r requirements.txt" in DEV.read_text()


def test_lock_pins_every_runtime_dependency_with_hashes():
    lock_text = LOCK.read_text()
    pinned = {
        _normalize(match.group(1))
        for match in re.finditer(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?==", lock_text, re.MULTILINE)
    }
    missing = _requirement_names(RUNTIME) - OLD_PYTHON_ONLY - pinned
    assert not missing, f"not pinned in requirements.lock: {sorted(missing)}"
    assert "--hash=sha256:" in lock_text


def test_modal_image_installs_the_lock_file():
    assert "requirements.lock" in (API_ROOT / "modal_app.py").read_text()
