"""Configuration system for Explainer Studio.

Implements ExplainerConfig with resolve() classmethod that merges
configuration from CLI args > environment variables > config file > defaults.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from explainer.core.errors import ConfigError

# Default config file location
DEFAULT_CONFIG_PATH = Path.home() / ".explainer" / "config.toml"

# Mapping of environment variable names to config field names
_ENV_FIELD_MAP: dict[str, str] = {
    "EXPLAINER_LLM": "llm",
    "EXPLAINER_TTS": "tts",
    "EXPLAINER_VOICE": "voice",
    "EXPLAINER_FPS": "fps",
    "EXPLAINER_RESOLUTION": "resolution",
    "EXPLAINER_KEEP_ARTIFACTS": "keep_artifacts",
}

# Mapping of LLM model prefixes to accepted API key env vars. Any one of the
# listed names satisfies the check; the first is the canonical/preferred name.
# Google issues a single credential that different tools name differently, so
# both GOOGLE_API_KEY and GEMINI_API_KEY are accepted — matching litellm, which
# reads GOOGLE_API_KEY first and falls back to GEMINI_API_KEY.
_LLM_API_KEY_MAP: dict[str, tuple[str, ...]] = {
    "openai": ("OPENAI_API_KEY",),
    "gpt": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "claude": ("ANTHROPIC_API_KEY",),
    "gemini": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "google": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "moonshot": ("MOONSHOT_API_KEY",),
    "kimi": ("MOONSHOT_API_KEY",),
    "deepseek": ("DEEPSEEK_API_KEY",),
}

# TTS providers that require API keys, same "any one of these" semantics.
_TTS_API_KEY_MAP: dict[str, tuple[str, ...]] = {
    "elevenlabs": ("ELEVENLABS_API_KEY",),
    "azure": ("AZURE_SPEECH_KEY",),
    "openai": ("OPENAI_API_KEY",),
}

# TTS providers with a working adapter. The other names in _TTS_API_KEY_MAP are
# reserved for future adapters. Pipeline checks this at construction time so a
# request for an unimplemented provider fails loudly instead of quietly
# substituting a different voice.
IMPLEMENTED_TTS: frozenset[str] = frozenset({"edge", "openai"})


def _describe_keys(names: tuple[str, ...]) -> str:
    """Render accepted env var names for an error message."""
    if len(names) == 1:
        return names[0]
    return " or ".join([", ".join(names[:-1]), names[-1]])


def _read_toml(path: Path) -> dict[str, Any]:
    """Read a TOML file, using tomllib (3.11+) or tomli as fallback."""
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        try:
            import tomli as tomllib  # type: ignore[import-not-found, unused-ignore]
        except ImportError as exc:
            raise ConfigError(
                "Cannot read config file: 'tomli' package is required for "
                "Python < 3.11. Install with: pip install tomli"
            ) from exc

    with open(path, "rb") as f:
        data: dict[str, Any] = tomllib.load(f)
        return data


def _parse_bool(value: str) -> bool:
    """Parse a boolean from a string env var value."""
    return value.lower() in ("1", "true", "yes", "on")


class ExplainerConfig(BaseModel):
    """Configuration for Explainer Studio pipeline.

    Fields:
        llm: LLM model string (e.g. "openai/gpt-5.6"). None uses heuristic fallback.
        tts: TTS provider name. Default "edge" (free, no API key).
        voice: Voice ID for TTS provider. None uses provider default.
        fps: Frames per second for rendering. Default 24.
        resolution: Output resolution. Default "720p".
        keep_artifacts: Whether to keep work directory after generation. Default False.
    """

    llm: str | None = None
    tts: str = "edge"
    voice: str | None = None
    fps: int = 24
    resolution: str = "720p"
    keep_artifacts: bool = False

    @classmethod
    def resolve(
        cls,
        cli_args: dict[str, Any] | None = None,
        env: dict[str, str] | None = None,
        config_file: Path | None = None,
    ) -> ExplainerConfig:
        """Merge configuration sources with precedence: CLI > env vars > config file > defaults.

        Args:
            cli_args: Dict of CLI arguments. Only non-None values are used.
            env: Dict of environment variables. If None, uses os.environ.
            config_file: Path to TOML config file. If None, checks default location.

        Returns:
            A fully resolved ExplainerConfig instance.

        Raises:
            ConfigError: If a required API key is missing for the configured provider.
        """
        if cli_args is None:
            cli_args = {}
        if env is None:
            env = dict(os.environ)
        if config_file is None:
            config_file = DEFAULT_CONFIG_PATH

        # Layer 1: Start with defaults (handled by pydantic defaults)
        merged: dict[str, Any] = {}

        # Layer 2: Config file (lowest precedence after defaults)
        if config_file.is_file():
            try:
                file_data = _read_toml(config_file)
            except (OSError, ValueError) as exc:
                raise ConfigError(
                    f"Failed to read config file {config_file}: {exc}"
                ) from exc
            # Only pick known fields from TOML
            for field_name in cls.model_fields:
                if field_name in file_data:
                    merged[field_name] = file_data[field_name]

        # Layer 3: Environment variables (override config file)
        for env_var, field_name in _ENV_FIELD_MAP.items():
            value = env.get(env_var)
            if value is not None:
                # Type coercion for non-string fields
                if field_name == "fps":
                    try:
                        merged[field_name] = int(value)
                    except ValueError as exc:
                        raise ConfigError(
                            f"Invalid value for {env_var}: expected integer, got '{value}'"
                        ) from exc
                elif field_name == "keep_artifacts":
                    merged[field_name] = _parse_bool(value)
                else:
                    merged[field_name] = value

        # Layer 4: CLI args (highest precedence, only non-None values)
        for key, value in cli_args.items():
            if value is not None:
                merged[key] = value

        # Build config instance
        config = cls(**merged)

        # Validate API keys
        _validate_api_keys(config, env)

        return config


def _validate_api_keys(config: ExplainerConfig, env: dict[str, str]) -> None:
    """Raise ConfigError if required API keys are missing.

    Does NOT raise for providers that don't need keys (edge-tts, heuristic LLM).
    """
    # Check LLM API key
    if config.llm is not None and config.llm != "heuristic":
        # Determine which key is needed from the model string prefix
        model_lower = config.llm.lower()
        accepted_keys: tuple[str, ...] | None = None

        for prefix, key_vars in _LLM_API_KEY_MAP.items():
            if model_lower.startswith(prefix):
                accepted_keys = key_vars
                break

        if accepted_keys and not any(env.get(name) for name in accepted_keys):
            raise ConfigError(
                f"{_describe_keys(accepted_keys)} required when using "
                f"'{config.llm}' models. "
                f"Set it via environment variable or ~/.explainer/config.toml"
            )

    # Check TTS API key
    tts_lower = config.tts.lower()
    if tts_lower in _TTS_API_KEY_MAP:
        accepted_keys = _TTS_API_KEY_MAP[tts_lower]
        if not any(env.get(name) for name in accepted_keys):
            raise ConfigError(
                f"{_describe_keys(accepted_keys)} required when using "
                f"'{config.tts}' TTS provider. "
                f"Set it via environment variable or ~/.explainer/config.toml"
            )
