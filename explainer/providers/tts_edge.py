"""Edge-TTS adapter — free, no API key, 300+ multilingual voices."""

from __future__ import annotations

import asyncio
import re
import subprocess
from pathlib import Path

import edge_tts

from explainer.core.errors import NarrationError
from explainer.providers.tts_base import TTSProvider, Voice

# Default timeout for a single TTS call (seconds).
_TTS_TIMEOUT = 30.0

# Default voice when none specified.
_DEFAULT_VOICE = "en-US-AriaNeural"


class EdgeTTSProvider:
    """TTS provider using the free Microsoft Edge TTS service.

    Implements the TTSProvider protocol with retry logic (one retry per scene)
    and a 30-second timeout on each TTS attempt.
    """

    def __init__(self, *, timeout: float = _TTS_TIMEOUT) -> None:
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Public API (TTSProvider protocol)
    # ------------------------------------------------------------------

    def synthesize(self, text: str, voice: str, out_path: Path) -> float:
        """Synthesize text to MP3 via edge-tts, return duration in seconds.

        Uses asyncio internally (edge-tts is async). Retries once on failure.
        Measures audio duration via ffprobe subprocess.

        Args:
            text: Narration text.
            voice: Voice ID (e.g., "en-US-AriaNeural"). If empty, uses default.
            out_path: Destination MP3 file path.

        Returns:
            Audio duration in seconds with centisecond precision.

        Raises:
            NarrationError: If TTS fails after one retry or ffprobe fails.
        """
        voice = voice or _DEFAULT_VOICE
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Attempt synthesis with one retry on failure.
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                self._run_synthesis(text, voice, out_path)
                break
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    # First failure — retry once.
                    continue
                raise NarrationError(
                    f"TTS failed after retry: {exc}",
                    scene_id=_extract_scene_id(out_path),
                ) from exc
        else:
            # Should not reach here, but guard against it.
            raise NarrationError(
                f"TTS failed: {last_error}",
                scene_id=_extract_scene_id(out_path),
            )

        # Measure duration via ffprobe.
        try:
            duration = self._measure_duration(out_path)
        except Exception as exc:
            raise NarrationError(
                f"ffprobe failed: {exc}",
                scene_id=_extract_scene_id(out_path),
            ) from exc

        return duration

    def list_voices(self, language: str) -> list[Voice]:
        """List available edge-tts voices filtered by language prefix.

        Args:
            language: Language prefix (e.g., "en", "zh-CN").

        Returns:
            List of matching Voice objects.
        """
        raw_voices = asyncio.run(edge_tts.list_voices())
        results: list[Voice] = []
        lang_lower = language.lower()
        for v in raw_voices:
            locale = str(v.get("Locale") or v.get("locale") or "")
            if locale.lower().startswith(lang_lower):
                results.append(
                    Voice(
                        id=str(v.get("ShortName") or v.get("short_name") or ""),
                        name=str(
                            v.get("FriendlyName") or v.get("friendly_name") or locale
                        ),
                        language=locale,
                    )
                )
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_synthesis(self, text: str, voice: str, out_path: Path) -> None:
        """Run edge-tts synthesis with timeout."""
        asyncio.run(self._async_synthesize(text, voice, out_path))

    async def _async_synthesize(self, text: str, voice: str, out_path: Path) -> None:
        """Async synthesis with timeout wrapper."""
        communicate = edge_tts.Communicate(text, voice)
        await asyncio.wait_for(
            communicate.save(str(out_path)),
            timeout=self._timeout,
        )

    @staticmethod
    def _measure_duration(audio_path: Path) -> float:
        """Measure audio duration via ffprobe subprocess.

        Returns duration in seconds with centisecond precision.
        """
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(audio_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"ffprobe exited with code {result.returncode}: {result.stderr.strip()}"
            )
        duration_str = result.stdout.strip()
        if not duration_str:
            raise RuntimeError("ffprobe returned empty duration")
        # Round to centisecond precision.
        return round(float(duration_str), 2)


def _extract_scene_id(path: Path) -> int:
    """Best-effort extraction of scene ID from output path filename.

    Expects patterns like 'scene1.mp3' or 'scene_2.mp3'. Falls back to 0.
    """
    stem = path.stem.lower()
    # Try to find digits after 'scene'
    match = re.search(r"scene\D*(\d+)", stem)
    if match:
        return int(match.group(1))
    return 0


# Type assertion: EdgeTTSProvider satisfies TTSProvider protocol.
_provider_check: TTSProvider = EdgeTTSProvider()
del _provider_check

__all__ = ["EdgeTTSProvider"]
