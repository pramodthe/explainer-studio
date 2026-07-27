"""Azure Cognitive Services TTS adapter — optional extra.

Install with: pip install explainer-studio[azure]
"""

from __future__ import annotations

from pathlib import Path

from explainer.providers.tts_base import Voice


class AzureTTSProvider:
    """TTS provider using Azure Cognitive Services Speech.

    This is an optional adapter. Install the required dependency with:
        pip install explainer-studio[azure]
    """

    def __init__(
        self, *, subscription_key: str | None = None, region: str = "eastus"
    ) -> None:
        raise ImportError(
            "The Azure TTS provider is not implemented in this release. "
            "Use the default 'edge' provider (free, no API key), or "
            "register your own via the 'explainer.providers' entry point. "
            "Tracking: explainer-studio[azure] is reserved for this adapter."
        )

    def synthesize(self, text: str, voice: str, out_path: Path) -> float:
        """Not reachable — __init__ raises ImportError."""
        raise ImportError(
            "The Azure TTS provider is not implemented in this release. "
            "Use the default 'edge' provider (free, no API key), or "
            "register your own via the 'explainer.providers' entry point. "
            "Tracking: explainer-studio[azure] is reserved for this adapter."
        )

    def list_voices(self, language: str) -> list[Voice]:
        """Not reachable — __init__ raises ImportError."""
        raise ImportError(
            "The Azure TTS provider is not implemented in this release. "
            "Use the default 'edge' provider (free, no API key), or "
            "register your own via the 'explainer.providers' entry point. "
            "Tracking: explainer-studio[azure] is reserved for this adapter."
        )


__all__ = ["AzureTTSProvider"]
