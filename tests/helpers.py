"""Shared test utilities for Explainer Studio test suite.

Provides:
- MockTTSProvider: generates silent MP3 of configurable duration
- Helper functions to check availability of Playwright/Chromium/ffmpeg
- Helper to create silent MP3 bytes
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from explainer.providers.tts_base import Voice

# ---------------------------------------------------------------------------
# Silent MP3 generation
# ---------------------------------------------------------------------------

# Minimal valid MP3 frame: a single MPEG-1 Layer 3, 128kbps, 44100Hz, stereo
# silence frame (all zero audio data). We repeat it to fill the desired duration.
# An MP3 frame at 128kbps/44100Hz contains 1152 samples ≈ 26.12ms per frame.
_MP3_FRAME_DURATION_MS = 26.12
_MP3_FRAME_SAMPLES = 1152
_MP3_SAMPLE_RATE = 44100


def _create_silent_mp3_bytes(duration_seconds: float) -> bytes:
    """Create a minimal silent MP3 file as bytes.

    Uses ffmpeg if available to generate a proper silent MP3.
    Falls back to a minimal valid MP3 byte sequence.

    Args:
        duration_seconds: Desired duration in seconds.

    Returns:
        Bytes representing a valid silent MP3 file.
    """
    if shutil.which("ffmpeg"):
        return _create_silent_mp3_via_ffmpeg(duration_seconds)
    return _create_minimal_silent_mp3(duration_seconds)


def _create_silent_mp3_via_ffmpeg(duration_seconds: float) -> bytes:
    """Generate a silent MP3 using ffmpeg subprocess."""
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-t",
            str(duration_seconds),
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            "-f",
            "mp3",
            "pipe:1",
        ],
        capture_output=True,
        timeout=10,
        check=False,
    )
    if result.returncode == 0 and result.stdout:
        return result.stdout
    # Fallback if ffmpeg fails for some reason
    return _create_minimal_silent_mp3(duration_seconds)


def _create_minimal_silent_mp3(duration_seconds: float) -> bytes:
    """Create a minimal valid MP3 with silence (frame-level construction).

    This produces a valid MP3 file with silence frames. Each frame
    is 417 bytes for MPEG1 Layer3 128kbps 44100Hz mono.
    """
    # MPEG1 Layer3 128kbps 44100Hz mono frame header
    # Sync word (0xFFE0) + MPEG1 + Layer3 + no CRC + 128kbps + 44100 + no padding + mono
    # 0xFF 0xFB 0x90 0x00
    frame_header = b"\xff\xfb\x90\x00"
    # Frame size for 128kbps, 44100Hz, mono, no padding:
    # frame_size = 144 * bitrate / sample_rate + padding = 144 * 128000 / 44100 = 417
    frame_size = 417
    # Fill rest of frame with zeros (silence)
    frame_body = b"\x00" * (frame_size - len(frame_header))
    single_frame = frame_header + frame_body

    # Calculate number of frames needed
    frames_needed = max(
        1, int(duration_seconds * _MP3_SAMPLE_RATE / _MP3_FRAME_SAMPLES)
    )

    return single_frame * frames_needed


def create_silent_mp3_file(path: Path, duration_seconds: float = 2.5) -> None:
    """Write a silent MP3 file to the given path.

    Args:
        path: Output file path.
        duration_seconds: Duration of silence.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _create_silent_mp3_bytes(duration_seconds)
    path.write_bytes(data)


# ---------------------------------------------------------------------------
# Mock TTS Provider
# ---------------------------------------------------------------------------


class MockTTSProvider:
    """Mock TTS provider that generates silent MP3 files of fixed duration.

    Implements the TTSProvider protocol for testing without network calls.
    """

    def __init__(self, duration: float = 2.5) -> None:
        """Initialize with a fixed duration for all synthesized audio.

        Args:
            duration: Duration in seconds for all generated audio (default 2.5s).
        """
        self.duration = duration
        self.calls: list[dict] = []  # Track calls for assertion

    def synthesize(self, text: str, voice: str, out_path: Path) -> float:
        """Generate a silent MP3 at out_path and return the fixed duration.

        Args:
            text: The narration text (recorded but not used).
            voice: Voice ID (recorded but not used).
            out_path: Where to write the silent MP3.

        Returns:
            The configured duration in seconds.
        """
        self.calls.append({"text": text, "voice": voice, "out_path": out_path})
        create_silent_mp3_file(out_path, self.duration)
        return self.duration

    def list_voices(self, language: str) -> list[Voice]:
        """Return a single mock voice for any language.

        Args:
            language: Language prefix (ignored).

        Returns:
            List with one mock voice.
        """
        return [Voice(id="mock-voice-1", name="Mock Voice", language=language or "en")]


# ---------------------------------------------------------------------------
# Availability checks
# ---------------------------------------------------------------------------


def is_playwright_available() -> bool:
    """Check if Playwright is importable."""
    try:
        import playwright  # noqa: F401

        return True
    except ImportError:
        return False


def is_chromium_installed() -> bool:
    """Check if Playwright's Chromium browser is installed and launchable."""
    if not is_playwright_available():
        return False
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            browser.close()
            return True
    # Capability probe: any launch failure means "not usable here".
    except Exception:  # noqa: BLE001
        return False


def is_ffmpeg_available() -> bool:
    """Check if ffmpeg is available on PATH."""
    return shutil.which("ffmpeg") is not None


def is_ffprobe_available() -> bool:
    """Check if ffprobe is available on PATH."""
    return shutil.which("ffprobe") is not None


# ---------------------------------------------------------------------------
# Pytest skip helpers
# ---------------------------------------------------------------------------


def requires_chromium():
    """Pytest marker to skip if Chromium is not available."""
    import pytest

    return pytest.mark.skipif(
        not is_chromium_installed(),
        reason="Playwright Chromium not installed (run: playwright install chromium)",
    )


def requires_ffmpeg():
    """Pytest marker to skip if ffmpeg is not available."""
    import pytest

    return pytest.mark.skipif(
        not is_ffmpeg_available(),
        reason="ffmpeg not available on PATH",
    )


def requires_ffprobe():
    """Pytest marker to skip if ffprobe is not available."""
    import pytest

    return pytest.mark.skipif(
        not is_ffprobe_available(),
        reason="ffprobe not available on PATH",
    )
