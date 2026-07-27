"""Unit tests for TTS provider interface and adapters."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from explainer.core.errors import NarrationError
from explainer.providers.tts_base import TTSProvider, Voice
from explainer.providers.tts_edge import EdgeTTSProvider

# ---------------------------------------------------------------------------
# Voice model tests
# ---------------------------------------------------------------------------


class TestVoice:
    """Tests for the Voice pydantic model."""

    def test_creates_voice_with_all_fields(self):
        v = Voice(id="en-US-AriaNeural", name="Aria", language="en-US")
        assert v.id == "en-US-AriaNeural"
        assert v.name == "Aria"
        assert v.language == "en-US"

    def test_voice_serialization(self):
        v = Voice(id="zh-CN-XiaoxiaoNeural", name="Xiaoxiao", language="zh-CN")
        data = v.model_dump()
        assert data == {
            "id": "zh-CN-XiaoxiaoNeural",
            "name": "Xiaoxiao",
            "language": "zh-CN",
        }

    def test_voice_from_dict(self):
        v = Voice.model_validate({"id": "test-voice", "name": "Test", "language": "en"})
        assert v.id == "test-voice"


# ---------------------------------------------------------------------------
# TTSProvider Protocol tests
# ---------------------------------------------------------------------------


class TestTTSProviderProtocol:
    """Tests for the TTSProvider protocol compliance."""

    def test_edge_provider_is_tts_provider(self):
        """EdgeTTSProvider should satisfy the TTSProvider protocol."""
        provider = EdgeTTSProvider.__new__(EdgeTTSProvider)
        assert isinstance(provider, TTSProvider)

    def test_protocol_has_synthesize(self):
        assert hasattr(TTSProvider, "synthesize")

    def test_protocol_has_list_voices(self):
        assert hasattr(TTSProvider, "list_voices")


# ---------------------------------------------------------------------------
# EdgeTTSProvider tests
# ---------------------------------------------------------------------------


class TestEdgeTTSProviderSynthesize:
    """Tests for EdgeTTSProvider.synthesize with mocked edge-tts and ffprobe."""

    @patch("explainer.providers.tts_edge.subprocess.run")
    @patch("explainer.providers.tts_edge.asyncio.run")
    def test_synthesize_success(self, mock_asyncio_run, mock_subprocess_run, tmp_path):
        """Successful synthesis returns duration from ffprobe."""
        out_path = tmp_path / "scene1.mp3"
        # Make asyncio.run succeed (simulates edge-tts writing the file).
        mock_asyncio_run.return_value = None
        # Simulate file creation (edge-tts would create it).
        out_path.write_bytes(b"fake mp3 data")

        # ffprobe returns duration string.
        mock_subprocess_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="5.23\n", stderr=""
        )

        provider = EdgeTTSProvider()
        duration = provider.synthesize("Hello world", "en-US-AriaNeural", out_path)

        assert duration == 5.23
        mock_asyncio_run.assert_called_once()
        mock_subprocess_run.assert_called_once()

    @patch("explainer.providers.tts_edge.subprocess.run")
    @patch("explainer.providers.tts_edge.asyncio.run")
    def test_synthesize_uses_default_voice_when_empty(
        self, mock_asyncio_run, mock_subprocess_run, tmp_path
    ):
        """Empty voice string falls back to default."""
        out_path = tmp_path / "scene1.mp3"
        mock_asyncio_run.return_value = None
        out_path.write_bytes(b"fake")
        mock_subprocess_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="3.50\n", stderr=""
        )

        provider = EdgeTTSProvider()
        provider.synthesize("Test", "", out_path)

        # Verify asyncio.run was called (synthesis happened).
        mock_asyncio_run.assert_called_once()

    @patch("explainer.providers.tts_edge.subprocess.run")
    @patch("explainer.providers.tts_edge.asyncio.run")
    def test_synthesize_retries_once_on_failure(
        self, mock_asyncio_run, mock_subprocess_run, tmp_path
    ):
        """First failure triggers retry; second success returns duration."""
        out_path = tmp_path / "scene2.mp3"

        # First call raises, second succeeds.
        mock_asyncio_run.side_effect = [RuntimeError("network error"), None]
        out_path.write_bytes(b"fake")
        mock_subprocess_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="4.10\n", stderr=""
        )

        provider = EdgeTTSProvider()
        duration = provider.synthesize("Retry test", "en-US-AriaNeural", out_path)

        assert duration == 4.10
        assert mock_asyncio_run.call_count == 2

    @patch("explainer.providers.tts_edge.asyncio.run")
    def test_synthesize_raises_narration_error_after_two_failures(
        self, mock_asyncio_run, tmp_path
    ):
        """Two consecutive failures raise NarrationError."""
        out_path = tmp_path / "scene3.mp3"
        mock_asyncio_run.side_effect = RuntimeError("permanent failure")

        provider = EdgeTTSProvider()
        with pytest.raises(NarrationError) as exc_info:
            provider.synthesize("Fail test", "en-US-AriaNeural", out_path)

        assert exc_info.value.scene_id == 3
        assert (
            "retry" in str(exc_info.value).lower()
            or "failed" in str(exc_info.value).lower()
        )

    @patch("explainer.providers.tts_edge.subprocess.run")
    @patch("explainer.providers.tts_edge.asyncio.run")
    def test_synthesize_raises_on_ffprobe_failure(
        self, mock_asyncio_run, mock_subprocess_run, tmp_path
    ):
        """ffprobe failure raises NarrationError."""
        out_path = tmp_path / "scene1.mp3"
        mock_asyncio_run.return_value = None
        out_path.write_bytes(b"fake")

        mock_subprocess_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="ffprobe: file not found"
        )

        provider = EdgeTTSProvider()
        with pytest.raises(NarrationError) as exc_info:
            provider.synthesize("Test", "en-US-AriaNeural", out_path)

        assert "ffprobe" in str(exc_info.value).lower()

    @patch("explainer.providers.tts_edge.subprocess.run")
    @patch("explainer.providers.tts_edge.asyncio.run")
    def test_synthesize_rounds_to_centisecond(
        self, mock_asyncio_run, mock_subprocess_run, tmp_path
    ):
        """Duration is rounded to centisecond precision."""
        out_path = tmp_path / "scene1.mp3"
        mock_asyncio_run.return_value = None
        out_path.write_bytes(b"fake")
        mock_subprocess_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="12.345678\n", stderr=""
        )

        provider = EdgeTTSProvider()
        duration = provider.synthesize("Test", "en-US-AriaNeural", out_path)

        assert duration == 12.35

    @patch("explainer.providers.tts_edge.subprocess.run")
    @patch("explainer.providers.tts_edge.asyncio.run")
    def test_synthesize_creates_parent_directories(
        self, mock_asyncio_run, mock_subprocess_run, tmp_path
    ):
        """Output path parent directories are created if they don't exist."""
        out_path = tmp_path / "nested" / "deep" / "scene1.mp3"
        mock_asyncio_run.return_value = None
        # Simulate file creation after mkdir.
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"fake")
        mock_subprocess_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="2.00\n", stderr=""
        )

        provider = EdgeTTSProvider()
        duration = provider.synthesize("Nested", "en-US-AriaNeural", out_path)

        assert duration == 2.00


class TestEdgeTTSProviderListVoices:
    """Tests for EdgeTTSProvider.list_voices with mocked edge_tts.list_voices."""

    @patch("explainer.providers.tts_edge.edge_tts.list_voices")
    def test_list_voices_filters_by_language(self, mock_list_voices):
        """Voices are filtered by language prefix."""
        mock_list_voices.return_value = [
            {
                "ShortName": "en-US-AriaNeural",
                "FriendlyName": "Aria",
                "Locale": "en-US",
            },
            {
                "ShortName": "en-GB-SoniaNeural",
                "FriendlyName": "Sonia",
                "Locale": "en-GB",
            },
            {
                "ShortName": "zh-CN-XiaoxiaoNeural",
                "FriendlyName": "Xiaoxiao",
                "Locale": "zh-CN",
            },
        ]

        provider = EdgeTTSProvider.__new__(EdgeTTSProvider)
        provider._timeout = 30.0
        voices = provider.list_voices("en")

        assert len(voices) == 2
        assert all(v.language.startswith("en") for v in voices)

    @patch("explainer.providers.tts_edge.edge_tts.list_voices")
    def test_list_voices_returns_empty_for_no_match(self, mock_list_voices):
        """Returns empty list when no voices match the language."""
        mock_list_voices.return_value = [
            {
                "ShortName": "en-US-AriaNeural",
                "FriendlyName": "Aria",
                "Locale": "en-US",
            },
        ]

        provider = EdgeTTSProvider.__new__(EdgeTTSProvider)
        provider._timeout = 30.0
        voices = provider.list_voices("fr")

        assert voices == []

    @patch("explainer.providers.tts_edge.edge_tts.list_voices")
    def test_list_voices_case_insensitive(self, mock_list_voices):
        """Language matching is case-insensitive."""
        mock_list_voices.return_value = [
            {
                "ShortName": "en-US-AriaNeural",
                "FriendlyName": "Aria",
                "Locale": "en-US",
            },
        ]

        provider = EdgeTTSProvider.__new__(EdgeTTSProvider)
        provider._timeout = 30.0
        voices = provider.list_voices("EN")

        assert len(voices) == 1


# ---------------------------------------------------------------------------
# Stub provider tests
# ---------------------------------------------------------------------------


class TestStubProviders:
    """Tests for stub TTS providers that raise ImportError."""

    def test_elevenlabs_raises_import_error(self):
        from explainer.providers.tts_elevenlabs import ElevenLabsTTSProvider

        with pytest.raises(ImportError, match="elevenlabs"):
            ElevenLabsTTSProvider()

    def test_azure_raises_import_error(self):
        from explainer.providers.tts_azure import AzureTTSProvider

        with pytest.raises(ImportError, match="azure"):
            AzureTTSProvider()

    def test_elevenlabs_error_states_it_is_unimplemented(self):
        from explainer.providers.tts_elevenlabs import ElevenLabsTTSProvider

        with pytest.raises(ImportError, match="not implemented in this release"):
            ElevenLabsTTSProvider()

    def test_azure_error_states_it_is_unimplemented(self):
        from explainer.providers.tts_azure import AzureTTSProvider

        with pytest.raises(ImportError, match="not implemented in this release"):
            AzureTTSProvider()

    def test_openai_provider_is_implemented(self):
        """OpenAI TTS has a real adapter; it must not be a stub."""
        from explainer.providers.tts_openai import OpenAITTSProvider

        assert callable(OpenAITTSProvider.synthesize)
        assert callable(OpenAITTSProvider.list_voices)

    def test_openai_requires_a_key(self, monkeypatch):
        """Without a key it raises NarrationError, not a stub ImportError."""
        from explainer.core.errors import NarrationError
        from explainer.providers.tts_openai import OpenAITTSProvider

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(NarrationError, match="OPENAI_API_KEY"):
            OpenAITTSProvider()

    def test_openai_lists_builtin_voices(self):
        from explainer.providers.tts_openai import OpenAITTSProvider

        voices = OpenAITTSProvider.list_voices(object(), "en")  # type: ignore[arg-type]
        ids = [v.id for v in voices]
        assert "marin" in ids and "cedar" in ids
        assert len(ids) == 13
