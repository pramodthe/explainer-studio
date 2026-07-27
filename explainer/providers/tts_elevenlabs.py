"""ElevenLabs TTS adapter — optional extra.

Install with: pip install explainer-studio[elevenlabs]
"""

from __future__ import annotations

from pathlib import Path

from explainer.providers.tts_base import Voice


class ElevenLabsTTSProvider:
    """TTS provider using ElevenLabs API.

    This is an optional adapter. Install the required dependency with:
        pip install explainer-studio[elevenlabs]
    """

    def __init__(self, *, api_key: str | None = None) -> None:
        raise ImportError(
            "The ElevenLabs TTS provider is not implemented in this release. "
            "Use the default 'edge' provider (free, no API key), or "
            "register your own via the 'explainer.providers' entry point. "
            "Tracking: explainer-studio[elevenlabs] is reserved for this adapter."
        )

    def synthesize(self, text: str, voice: str, out_path: Path) -> float:
        """Not reachable — __init__ raises ImportError."""
        raise ImportError(
            "The ElevenLabs TTS provider is not implemented in this release. "
            "Use the default 'edge' provider (free, no API key), or "
            "register your own via the 'explainer.providers' entry point. "
            "Tracking: explainer-studio[elevenlabs] is reserved for this adapter."
        )

    def list_voices(self, language: str) -> list[Voice]:
        """Not reachable — __init__ raises ImportError."""
        raise ImportError(
            "The ElevenLabs TTS provider is not implemented in this release. "
            "Use the default 'edge' provider (free, no API key), or "
            "register your own via the 'explainer.providers' entry point. "
            "Tracking: explainer-studio[elevenlabs] is reserved for this adapter."
        )


__all__ = ["ElevenLabsTTSProvider"]
