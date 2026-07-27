"""Unit tests for explainer.config module."""

from __future__ import annotations

from pathlib import Path

import pytest

from explainer.config import ExplainerConfig, _parse_bool
from explainer.core.errors import ConfigError

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    """ExplainerConfig should provide sane defaults."""

    def test_default_values(self):
        config = ExplainerConfig()
        assert config.llm is None
        assert config.tts == "edge"
        assert config.voice is None
        assert config.fps == 24
        assert config.resolution == "720p"
        assert config.keep_artifacts is False

    def test_resolve_with_no_sources(self):
        """resolve() with empty CLI, no env vars, and no config file → defaults."""
        config = ExplainerConfig.resolve(
            cli_args={}, env={}, config_file=Path("/nonexistent")
        )
        assert config.llm is None
        assert config.tts == "edge"
        assert config.fps == 24
        assert config.resolution == "720p"
        assert config.keep_artifacts is False


# ---------------------------------------------------------------------------
# Config file (TOML)
# ---------------------------------------------------------------------------


class TestConfigFile:
    """Config file values should be loaded and overridden by higher sources."""

    def test_reads_config_file(self, tmp_path: Path):
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            'llm = "openai/gpt-5.6"\n'
            'tts = "elevenlabs"\n'
            "fps = 24\n"
            'resolution = "1080p"\n'
        )
        config = ExplainerConfig.resolve(
            cli_args={},
            env={"OPENAI_API_KEY": "sk-test", "ELEVENLABS_API_KEY": "el-test"},
            config_file=config_file,
        )
        assert config.llm == "openai/gpt-5.6"
        assert config.tts == "elevenlabs"
        assert config.fps == 24
        assert config.resolution == "1080p"

    def test_ignores_missing_config_file(self):
        """Non-existent config file should not raise."""
        config = ExplainerConfig.resolve(
            cli_args={}, env={}, config_file=Path("/does/not/exist.toml")
        )
        assert config.tts == "edge"

    def test_ignores_unknown_keys_in_toml(self, tmp_path: Path):
        config_file = tmp_path / "config.toml"
        config_file.write_text('tts = "edge"\nunknown_key = "should be ignored"\n')
        config = ExplainerConfig.resolve(cli_args={}, env={}, config_file=config_file)
        assert config.tts == "edge"


# ---------------------------------------------------------------------------
# Environment variables
# ---------------------------------------------------------------------------


class TestEnvironmentVariables:
    """Environment variables override config file values."""

    def test_env_overrides_config_file(self, tmp_path: Path):
        config_file = tmp_path / "config.toml"
        config_file.write_text('tts = "elevenlabs"\n')

        config = ExplainerConfig.resolve(
            cli_args={},
            env={"EXPLAINER_TTS": "edge", "ELEVENLABS_API_KEY": "key"},
            config_file=config_file,
        )
        assert config.tts == "edge"

    def test_env_fps_parsed_as_int(self):
        config = ExplainerConfig.resolve(
            cli_args={},
            env={"EXPLAINER_FPS": "30"},
            config_file=Path("/nonexistent"),
        )
        assert config.fps == 30

    def test_env_fps_invalid_raises_config_error(self):
        with pytest.raises(ConfigError, match="Invalid value for EXPLAINER_FPS"):
            ExplainerConfig.resolve(
                cli_args={},
                env={"EXPLAINER_FPS": "not_a_number"},
                config_file=Path("/nonexistent"),
            )

    def test_env_keep_artifacts_truthy(self):
        for val in ("1", "true", "True", "yes", "on"):
            config = ExplainerConfig.resolve(
                cli_args={},
                env={"EXPLAINER_KEEP_ARTIFACTS": val},
                config_file=Path("/nonexistent"),
            )
            assert config.keep_artifacts is True

    def test_env_keep_artifacts_falsy(self):
        config = ExplainerConfig.resolve(
            cli_args={},
            env={"EXPLAINER_KEEP_ARTIFACTS": "0"},
            config_file=Path("/nonexistent"),
        )
        assert config.keep_artifacts is False

    def test_env_llm_sets_model(self):
        config = ExplainerConfig.resolve(
            cli_args={},
            env={"EXPLAINER_LLM": "openai/gpt-5.6", "OPENAI_API_KEY": "sk-test"},
            config_file=Path("/nonexistent"),
        )
        assert config.llm == "openai/gpt-5.6"


# ---------------------------------------------------------------------------
# CLI arguments
# ---------------------------------------------------------------------------


class TestCLIArgs:
    """CLI args have highest precedence and override everything."""

    def test_cli_overrides_env(self):
        config = ExplainerConfig.resolve(
            cli_args={"tts": "openai", "fps": 24},
            env={
                "EXPLAINER_TTS": "edge",
                "EXPLAINER_FPS": "30",
                "OPENAI_API_KEY": "sk-test",
            },
            config_file=Path("/nonexistent"),
        )
        assert config.tts == "openai"
        assert config.fps == 24

    def test_cli_overrides_config_file(self, tmp_path: Path):
        config_file = tmp_path / "config.toml"
        config_file.write_text('resolution = "1080p"\n')

        config = ExplainerConfig.resolve(
            cli_args={"resolution": "720p"},
            env={},
            config_file=config_file,
        )
        assert config.resolution == "720p"

    def test_cli_none_values_ignored(self):
        """None values in CLI args should NOT override lower layers."""
        config = ExplainerConfig.resolve(
            cli_args={"llm": None, "tts": None, "fps": None},
            env={"EXPLAINER_TTS": "elevenlabs", "ELEVENLABS_API_KEY": "key"},
            config_file=Path("/nonexistent"),
        )
        assert config.tts == "elevenlabs"


# ---------------------------------------------------------------------------
# Precedence integration
# ---------------------------------------------------------------------------


class TestPrecedence:
    """Full precedence chain: CLI > env > config file > defaults."""

    def test_full_precedence_chain(self, tmp_path: Path):
        config_file = tmp_path / "config.toml"
        config_file.write_text('tts = "azure"\nfps = 24\nresolution = "1080p"\n')
        config = ExplainerConfig.resolve(
            cli_args={"fps": 30},  # CLI wins for fps
            env={
                "EXPLAINER_TTS": "elevenlabs",  # env wins over file for tts
                "ELEVENLABS_API_KEY": "key",
            },
            config_file=config_file,  # file provides resolution
        )
        assert config.fps == 30  # CLI
        assert config.tts == "elevenlabs"  # env
        assert config.resolution == "1080p"  # config file


# ---------------------------------------------------------------------------
# API key validation
# ---------------------------------------------------------------------------


class TestAPIKeyValidation:
    """ConfigError raised for missing API keys."""

    def test_missing_openai_key_raises(self):
        with pytest.raises(ConfigError, match="OPENAI_API_KEY required"):
            ExplainerConfig.resolve(
                cli_args={"llm": "openai/gpt-5.6"},
                env={},
                config_file=Path("/nonexistent"),
            )

    def test_missing_anthropic_key_raises(self):
        with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY required"):
            ExplainerConfig.resolve(
                cli_args={"llm": "anthropic/claude-sonnet-5"},
                env={},
                config_file=Path("/nonexistent"),
            )

    def test_missing_elevenlabs_key_raises(self):
        with pytest.raises(ConfigError, match="ELEVENLABS_API_KEY required"):
            ExplainerConfig.resolve(
                cli_args={"tts": "elevenlabs"},
                env={},
                config_file=Path("/nonexistent"),
            )

    def test_edge_tts_no_key_required(self):
        """edge-tts does not require an API key."""
        config = ExplainerConfig.resolve(
            cli_args={"tts": "edge"},
            env={},
            config_file=Path("/nonexistent"),
        )
        assert config.tts == "edge"

    def test_heuristic_llm_no_key_required(self):
        """heuristic LLM does not require an API key."""
        config = ExplainerConfig.resolve(
            cli_args={"llm": "heuristic"},
            env={},
            config_file=Path("/nonexistent"),
        )
        assert config.llm == "heuristic"

    def test_no_llm_configured_no_error(self):
        """If llm is None (heuristic fallback), no key is needed."""
        config = ExplainerConfig.resolve(
            cli_args={},
            env={},
            config_file=Path("/nonexistent"),
        )
        assert config.llm is None

    def test_openai_key_present_no_error(self):
        """With the correct key set, no error is raised."""
        config = ExplainerConfig.resolve(
            cli_args={"llm": "openai/gpt-5.6"},
            env={"OPENAI_API_KEY": "sk-test-key-123"},
            config_file=Path("/nonexistent"),
        )
        assert config.llm == "openai/gpt-5.6"

    def test_gpt_prefix_requires_openai_key(self):
        with pytest.raises(ConfigError, match="OPENAI_API_KEY required"):
            ExplainerConfig.resolve(
                cli_args={"llm": "gpt-5.6"},
                env={},
                config_file=Path("/nonexistent"),
            )

    def test_gemini_prefix_requires_a_google_key(self):
        with pytest.raises(ConfigError, match="GOOGLE_API_KEY or GEMINI_API_KEY"):
            ExplainerConfig.resolve(
                cli_args={"llm": "gemini/gemini-3.6-flash"},
                env={},
                config_file=Path("/nonexistent"),
            )

    def test_gemini_accepts_google_api_key(self):
        config = ExplainerConfig.resolve(
            cli_args={"llm": "gemini/gemini-3.6-flash"},
            env={"GOOGLE_API_KEY": "test-key"},
            config_file=Path("/nonexistent"),
        )
        assert config.llm == "gemini/gemini-3.6-flash"

    def test_gemini_accepts_gemini_api_key(self):
        """AI Studio hands out one credential; litellm accepts either name."""
        config = ExplainerConfig.resolve(
            cli_args={"llm": "gemini/gemini-3.6-flash"},
            env={"GEMINI_API_KEY": "test-key"},
            config_file=Path("/nonexistent"),
        )
        assert config.llm == "gemini/gemini-3.6-flash"

    def test_google_prefix_accepts_gemini_api_key(self):
        config = ExplainerConfig.resolve(
            cli_args={"llm": "google/gemini-3.6-flash"},
            env={"GEMINI_API_KEY": "test-key"},
            config_file=Path("/nonexistent"),
        )
        assert config.llm == "google/gemini-3.6-flash"

    def test_config_error_is_actionable(self):
        """Error message should suggest how to fix."""
        with pytest.raises(ConfigError) as exc_info:
            ExplainerConfig.resolve(
                cli_args={"llm": "openai/gpt-5.6"},
                env={},
                config_file=Path("/nonexistent"),
            )
        msg = str(exc_info.value)
        assert "environment variable" in msg or "config.toml" in msg

    def test_openai_tts_requires_key(self):
        with pytest.raises(ConfigError, match="OPENAI_API_KEY required"):
            ExplainerConfig.resolve(
                cli_args={"tts": "openai"},
                env={},
                config_file=Path("/nonexistent"),
            )

    def test_azure_tts_requires_key(self):
        with pytest.raises(ConfigError, match="AZURE_SPEECH_KEY required"):
            ExplainerConfig.resolve(
                cli_args={"tts": "azure"},
                env={},
                config_file=Path("/nonexistent"),
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    """Test internal helper functions."""

    def test_parse_bool_truthy(self):
        assert _parse_bool("1") is True
        assert _parse_bool("true") is True
        assert _parse_bool("True") is True
        assert _parse_bool("yes") is True
        assert _parse_bool("on") is True

    def test_parse_bool_falsy(self):
        assert _parse_bool("0") is False
        assert _parse_bool("false") is False
        assert _parse_bool("no") is False
        assert _parse_bool("off") is False
