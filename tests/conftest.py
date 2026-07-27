"""Root conftest for Explainer Studio test suite.

Provides shared fixtures: mock TTS provider, golden script loading, tmp work dirs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.helpers import MockTTSProvider

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"
GOLDEN_SCRIPT_PATH = FIXTURES_DIR / "golden_script.json"


# ---------------------------------------------------------------------------
# Marker assignment
# ---------------------------------------------------------------------------

# Directory name -> marker. Applied automatically so `pytest -m unit` (used by
# CI) selects the whole suite without every module repeating `pytestmark`.
_DIR_MARKERS = {"unit": "unit", "golden": "golden", "e2e": "e2e"}


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Mark each test according to the tests/<dir>/ it lives in."""
    tests_root = Path(__file__).parent
    for item in items:
        try:
            relative = Path(item.fspath).relative_to(tests_root)
        except ValueError:
            continue
        if not relative.parts:
            continue
        marker = _DIR_MARKERS.get(relative.parts[0])
        if marker is not None:
            item.add_marker(getattr(pytest.mark, marker))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_tts() -> MockTTSProvider:
    """Provide a MockTTSProvider that generates 2.5s silent MP3s."""
    return MockTTSProvider(duration=2.5)


@pytest.fixture
def golden_script_data() -> dict:
    """Load the golden test script as a raw dict."""
    return json.loads(GOLDEN_SCRIPT_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def golden_script_path() -> Path:
    """Return the path to the golden test script JSON."""
    return GOLDEN_SCRIPT_PATH


@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    """Provide a temporary work directory for test artifacts."""
    wd = tmp_path / "work"
    wd.mkdir()
    return wd
