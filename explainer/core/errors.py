"""Typed exception hierarchy for Explainer Studio pipeline stages."""

from __future__ import annotations


class ExplainerError(Exception):
    """Base exception for all explainer pipeline errors.

    Attributes:
        stage: The pipeline stage where the error occurred.
        message: A human-readable description of the error.
    """

    stage: str = "unknown"

    def __init__(self, message: str, stage: str | None = None) -> None:
        if stage is not None:
            self.stage = stage
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        return f"[{self.stage}] {self.message}"


class ScriptValidationError(ExplainerError):
    """Raised when LLM output fails schema validation after retry."""

    stage = "scripting"

    def __init__(self, message: str) -> None:
        super().__init__(message, stage="scripting")


class NarrationError(ExplainerError):
    """Raised when TTS fails after retry or ffprobe fails.

    Attributes:
        scene_id: The ID of the scene whose narration failed.
    """

    stage = "narrating"

    def __init__(self, message: str, scene_id: int) -> None:
        self.scene_id = scene_id
        super().__init__(message, stage="narrating")

    def __str__(self) -> str:
        return f"[{self.stage}] scene {self.scene_id}: {self.message}"


class RenderError(ExplainerError):
    """Raised on template JS error, timeout, or Chromium crash.

    Attributes:
        scene_id: The ID of the scene that failed (None if crash before scene start).
        frame_index: The frame index at which failure occurred (None if not applicable).
    """

    stage = "rendering"

    def __init__(
        self,
        message: str,
        scene_id: int | None = None,
        frame_index: int | None = None,
    ) -> None:
        self.scene_id = scene_id
        self.frame_index = frame_index
        super().__init__(message, stage="rendering")

    def __str__(self) -> str:
        parts = [f"[{self.stage}]"]
        if self.scene_id is not None:
            parts.append(f"scene {self.scene_id}")
        if self.frame_index is not None:
            parts.append(f"frame {self.frame_index}")
        parts.append(self.message)
        return " ".join(parts)


class CompositionError(ExplainerError):
    """Raised when FFmpeg encoding or concat fails.

    Attributes:
        ffmpeg_stderr: FFmpeg stderr output truncated to 1024 characters.
    """

    stage = "composing"

    def __init__(self, message: str, ffmpeg_stderr: str) -> None:
        self.ffmpeg_stderr = ffmpeg_stderr[:1024]
        super().__init__(message, stage="composing")

    def __str__(self) -> str:
        return f"[{self.stage}] {self.message}\nffmpeg stderr: {self.ffmpeg_stderr}"


class ConfigError(ExplainerError):
    """Raised for missing API keys, invalid provider names, or missing ffmpeg.

    The message should explain what is missing and how to fix it.
    """

    stage = "config"

    def __init__(self, message: str) -> None:
        super().__init__(message, stage="config")


__all__ = [
    "CompositionError",
    "ConfigError",
    "ExplainerError",
    "NarrationError",
    "RenderError",
    "ScriptValidationError",
]
