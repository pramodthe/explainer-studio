"""Title template — opening scene with topic name and subtitle."""

from pathlib import Path


def get_path() -> Path:
    """Return the path to this template's directory."""
    return Path(__file__).parent
