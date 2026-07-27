"""TTS provider interface and Voice model for Explainer Studio."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class Voice(BaseModel):
    """A TTS voice descriptor.

    Attributes:
        id: Provider-specific voice identifier (e.g., "en-US-AriaNeural").
        name: Human-readable display name.
        language: BCP-47 language tag (e.g., "en-US", "zh-CN").
    """

    id: str
    name: str
    language: str


@runtime_checkable
class TTSProvider(Protocol):
    """Protocol that all TTS adapters must implement.

    Methods:
        synthesize: Convert text to speech, write MP3 to out_path, return duration in seconds.
        list_voices: List available voices filtered by language prefix.
    """

    def synthesize(self, text: str, voice: str, out_path: Path) -> float:
        """Synthesize speech from text and write to an MP3 file.

        Args:
            text: The narration text to synthesize.
            voice: Provider-specific voice ID.
            out_path: Destination path for the generated MP3 file.

        Returns:
            Audio duration in seconds (centisecond precision).

        Raises:
            NarrationError: If synthesis fails after retry.
        """
        ...

    def list_voices(self, language: str) -> list[Voice]:
        """List available voices for the given language.

        Args:
            language: Language prefix to filter by (e.g., "en", "zh-CN").

        Returns:
            List of Voice objects matching the language filter.
        """
        ...


__all__ = ["TTSProvider", "Voice"]
