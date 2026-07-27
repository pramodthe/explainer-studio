"""OpenAI TTS adapter.

Install the optional dependency with: pip install explainer-studio[openai]
Requires OPENAI_API_KEY in the environment (or an explicit api_key argument).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from explainer.core.errors import NarrationError
from explainer.providers.tts_base import Voice

# Default speech model. Override per-instance with model=.
_DEFAULT_MODEL = "gpt-4o-mini-tts"
_DEFAULT_VOICE = "marin"

# Built-in voices for gpt-4o-mini-tts. Custom voices ("voice_123abc") are
# accepted too — they are passed through untouched.
_VOICES: tuple[tuple[str, str], ...] = (
    ("marin", "Marin — recommended, warm and clear"),
    ("cedar", "Cedar — recommended, steady and neutral"),
    ("alloy", "Alloy — balanced"),
    ("ash", "Ash — measured"),
    ("ballad", "Ballad — expressive"),
    ("coral", "Coral — bright"),
    ("echo", "Echo — even"),
    ("fable", "Fable — narrative"),
    ("nova", "Nova — energetic"),
    ("onyx", "Onyx — deep"),
    ("sage", "Sage — calm"),
    ("shimmer", "Shimmer — light"),
    ("verse", "Verse — conversational"),
)

_TIMEOUT_SECONDS = 60


class OpenAITTSProvider:
    """TTS provider backed by the OpenAI audio speech endpoint.

    Args:
        api_key: API key. Falls back to the OPENAI_API_KEY environment variable.
        model: Speech model id. Defaults to "gpt-4o-mini-tts".
        instructions: Optional style directions for the model, e.g.
            "Speak like a calm documentary narrator." Ignored by tts-1 models.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = _DEFAULT_MODEL,
        instructions: str | None = None,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError(
                "OpenAI TTS provider requires the 'openai' package. "
                "Install with: pip install explainer-studio[openai]"
            ) from exc

        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise NarrationError(
                "OPENAI_API_KEY required for the 'openai' TTS provider.",
                scene_id=0,
            )

        self._client = OpenAI(api_key=key, timeout=_TIMEOUT_SECONDS)
        self._model = model
        self._instructions = instructions

    def synthesize(self, text: str, voice: str, out_path: Path) -> float:
        """Synthesize narration to an MP3 and return its duration in seconds.

        Args:
            text: Narration text to speak.
            voice: Voice id (see list_voices). Empty uses the default.
            out_path: Destination MP3 path.

        Returns:
            Audio duration in seconds, centisecond precision. Scene length is
            derived from this value, so it must describe the written file.

        Raises:
            NarrationError: If the request fails or the audio is unreadable.
        """
        out_path.parent.mkdir(parents=True, exist_ok=True)
        kwargs: dict[str, object] = {
            "model": self._model,
            "voice": voice or _DEFAULT_VOICE,
            "input": text,
            "response_format": "mp3",
        }
        if self._instructions:
            kwargs["instructions"] = self._instructions

        try:
            response = self._client.audio.speech.create(**kwargs)  # type: ignore[arg-type]
            out_path.write_bytes(response.read())
        except Exception as exc:  # noqa: BLE001 - any client/transport failure
            raise NarrationError(
                f"OpenAI TTS request failed ({type(exc).__name__}): {exc}",
                scene_id=0,
            ) from exc

        return self._measure_duration(out_path)

    def list_voices(self, language: str) -> list[Voice]:
        """List built-in voices.

        The voices are multilingual and not filtered by language; `language` is
        accepted for protocol compatibility and reported back on each Voice.
        """
        return [
            Voice(id=vid, name=desc, language=language or "multi")
            for vid, desc in _VOICES
        ]

    @staticmethod
    def _measure_duration(audio_path: Path) -> float:
        """Measure audio duration via ffprobe."""
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
            raise NarrationError(
                f"ffprobe exited with code {result.returncode}: "
                f"{result.stderr.strip()}",
                scene_id=0,
            )
        duration_str = result.stdout.strip()
        if not duration_str:
            raise NarrationError("ffprobe returned empty duration", scene_id=0)
        return round(float(duration_str), 2)


__all__ = ["OpenAITTSProvider"]
