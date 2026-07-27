"""Pipeline orchestrator for Explainer Studio.

Coordinates the four-stage video generation pipeline:
Script Generation → Narration → Rendering → Composition.

Manages work directories, progress events, and artifact cleanup.
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from explainer.config import IMPLEMENTED_TTS, ExplainerConfig
from explainer.core.composer import Composer, CompositionJob
from explainer.core.errors import (
    ConfigError,
    ExplainerError,
    NarrationError,
    ScriptValidationError,
)
from explainer.core.registry import Registry
from explainer.core.renderer import Renderer, SceneRenderJob
from explainer.core.sanitize import (
    ANIMATION_CODE_FIELDS,
    sanitize_animation_markup,
    sanitize_scene_data,
    validate_animation_code,
)
from explainer.core.schema import Audience, SceneKind, Script
from explainer.providers.tts_base import TTSProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ProgressEvent:
    """Progress event emitted at stage transitions.

    Attributes:
        stage: Current pipeline stage name.
        pct: Progress percentage (0-100).
        message: Optional human-readable status message.
    """

    stage: str  # "scripting" | "narrating" | "rendering" | "composing" | "done"
    pct: float  # 0-100
    message: str = ""


@dataclass
class GenerateResult:
    """Result returned by Pipeline.generate() and Pipeline.render().

    Attributes:
        mp4_path: Path to the final output MP4 file.
        script: The Script used for generation.
        work_dir: Path to the work directory (may be cleaned up unless keep_artifacts=True).
    """

    mp4_path: Path
    script: Script
    work_dir: Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Default tail pad added to audio duration for scene timing.
_TAIL_PAD_SECONDS = 0.4


def _slugify(text: str, max_len: int = 60) -> str:
    """Convert text to a filesystem-safe slug.

    Lowercase, replace non-alphanumeric characters with dashes,
    collapse multiple dashes, trim to max_len, strip leading/trailing dashes.
    """
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    return slug[:max_len]


def _resolve_output_path(topic: str, out: str | None) -> Path:
    """Determine the output MP4 path.

    If out is provided, use it directly (ensure .mp4 extension).
    Otherwise, slugify the topic and place in the current directory.
    """
    if out:
        p = Path(out)
        if p.suffix.lower() != ".mp4":
            p = p.with_suffix(".mp4")
        return p
    slug = _slugify(topic)
    if not slug:
        slug = "explainer-output"
    return Path.cwd() / f"{slug}.mp4"


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class Pipeline:
    """Orchestrates script generation, narration, rendering, and composition.

    Args:
        llm: LLM model string (e.g. "openai/gpt-5.6") or None for heuristic.
        tts: TTS provider name (default "edge").
        voice: Voice ID for TTS (None uses provider default).
        on_progress: Callback receiving ProgressEvent at stage transitions.
    """

    def __init__(
        self,
        llm: str | None = None,
        tts: str = "edge",
        voice: str | None = None,
        on_progress: Callable[[ProgressEvent], None] | None = None,
    ) -> None:
        cli_args = {"llm": llm, "tts": tts, "voice": voice}
        self.config = ExplainerConfig.resolve(cli_args=cli_args)

        # Fail before any LLM spend rather than quietly narrating with a
        # different provider than the caller asked for.
        if self.config.tts not in IMPLEMENTED_TTS:
            available = ", ".join(sorted(IMPLEMENTED_TTS))
            raise ConfigError(
                f"TTS provider '{self.config.tts}' is not implemented in this "
                f"release. Available: {available}. Pick a voice with "
                f"'explainer voices', or register your own provider via the "
                f"'explainer.providers' entry point."
            )

        self.on_progress = on_progress

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        topic: str,
        *,
        language: str = "en",
        audience: str = "student",
        target_duration: int = 60,
        fps: int = 15,
        resolution: str = "720p",
        music: str | None = None,
        out: str | None = None,
        keep_artifacts: bool = False,
    ) -> GenerateResult:
        """Generate a video from a topic string through the full pipeline.

        Args:
            topic: The educational topic to explain.
            language: Language code (default "en").
            audience: Target audience ("kid", "student", "adult").
            target_duration: Target video duration in seconds.
            fps: Frames per second for rendering.
            resolution: Output resolution ("720p", "1080p", "vertical").
            music: Optional path to background music file.
            out: Output MP4 path (None to auto-generate from topic).
            keep_artifacts: If True, preserve work_dir after completion.

        Returns:
            GenerateResult with mp4_path, script, and work_dir.
        """
        work_dir = Path(tempfile.mkdtemp(prefix="explainer-"))

        try:
            # Stage 1: Script generation
            self._emit(
                ProgressEvent(stage="scripting", pct=0, message="Generating script...")
            )
            script = self._stage_scripting(
                topic=topic,
                language=language,
                audience=audience,
                target_duration=target_duration,
                work_dir=work_dir,
            )
            self._emit(ProgressEvent(stage="scripting", pct=25, message="Script ready"))

            # Stages 2-4: shared with render()
            result = self._execute_from_narration(
                script=script,
                fps=fps,
                resolution=resolution,
                music=music,
                out=out,
                keep_artifacts=keep_artifacts,
                work_dir=work_dir,
                topic=topic,
            )
            return result

        except ExplainerError:
            # Pipeline errors propagate without cleanup modification
            if not keep_artifacts:
                self._cleanup(work_dir)
            raise
        except Exception:
            if not keep_artifacts:
                self._cleanup(work_dir)
            raise

    def render(
        self,
        script: Script,
        *,
        out: str | None = None,
        fps: int = 15,
        resolution: str = "720p",
        music: str | None = None,
        keep_artifacts: bool = False,
        on_progress: Callable[[ProgressEvent], None] | None = None,
    ) -> GenerateResult:
        """Render a video from a pre-built Script (skips script generation).

        Args:
            script: A validated Script object.
            out: Output MP4 path (None to auto-generate from script topic).
            fps: Frames per second for rendering.
            resolution: Output resolution.
            music: Optional background music file path.
            keep_artifacts: If True, preserve work_dir.
            on_progress: Override progress callback for this render call.

        Returns:
            GenerateResult with mp4_path, script, and work_dir.
        """
        # Allow per-call progress override
        original_progress = self.on_progress
        if on_progress is not None:
            self.on_progress = on_progress

        work_dir = Path(tempfile.mkdtemp(prefix="explainer-"))

        try:
            # Save script to work_dir
            script.to_file(work_dir / "script.json")

            result = self._execute_from_narration(
                script=script,
                fps=fps,
                resolution=resolution,
                music=music,
                out=out,
                keep_artifacts=keep_artifacts,
                work_dir=work_dir,
                topic=script.topic,
            )
            return result

        except ExplainerError:
            if not keep_artifacts:
                self._cleanup(work_dir)
            raise
        except Exception:
            if not keep_artifacts:
                self._cleanup(work_dir)
            raise
        finally:
            self.on_progress = original_progress

    # ------------------------------------------------------------------
    # Internal stage methods
    # ------------------------------------------------------------------

    def _stage_scripting(
        self,
        topic: str,
        language: str,
        audience: str,
        target_duration: int,
        work_dir: Path,
    ) -> Script:
        """Stage 1: Generate script via LLM provider."""
        from explainer.providers.llm_base import (
            LLMProvider,
            ScriptRequest,
            TemplateInfo,
        )
        from explainer.providers.llm_heuristic import HeuristicProvider

        # Discover templates for the request
        registry = Registry()
        registry.discover()
        templates = registry.list_templates()
        available_templates = [
            TemplateInfo(kind=t.kind.value, name=t.name, schema=t.data_schema)
            for t in templates
        ]

        # `audience` arrives as a plain str from the public API and the CLI;
        # pydantic rejects anything outside Audience at construction time.
        request = ScriptRequest(
            topic=topic,
            language=language,
            audience=cast(Audience, audience),
            target_duration=target_duration,
            available_templates=available_templates,
        )

        # Resolve LLM provider
        provider: LLMProvider
        if self.config.llm is None or self.config.llm == "heuristic":
            provider = HeuristicProvider()
        else:
            from explainer.providers.llm_litellm import LiteLLMProvider

            provider = LiteLLMProvider(model=self.config.llm)

        script = provider.generate_script(request)

        # LiteLLM already retries once on animation violations inside its
        # generate_script loop. Re-check here so heuristic / third-party
        # providers fail closed before we write the script artifact.
        self._validate_animation_scenes(script)

        # Save script to work_dir
        script.to_file(work_dir / "script.json")

        return script

    def _stage_narrating(
        self,
        script: Script,
        work_dir: Path,
    ) -> dict[int, float]:
        """Stage 2: Synthesize narration for each scene, return duration map.

        Returns:
            Dict mapping scene_id to scene duration (audio + tail pad).
        """
        # Resolve TTS provider. Never fall back to a different provider than the
        # caller asked for — a silent substitution would change the voice
        # without telling anyone.
        tts_provider: TTSProvider
        if self.config.tts == "edge":
            from explainer.providers.tts_edge import EdgeTTSProvider

            tts_provider = EdgeTTSProvider()
        elif self.config.tts == "openai":
            from explainer.providers.tts_openai import OpenAITTSProvider

            tts_provider = OpenAITTSProvider()
        else:
            raise NarrationError(
                f"TTS provider '{self.config.tts}' is not implemented in this "
                f"release; refusing to silently substitute 'edge'.",
                scene_id=0,
            )

        voice = self.config.voice or ""
        audio_dir = work_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)

        duration_map: dict[int, float] = {}
        total_scenes = len(script.scenes)

        for i, scene in enumerate(script.scenes):
            out_path = audio_dir / f"scene{scene.id}.mp3"
            audio_duration = tts_provider.synthesize(
                text=scene.narration,
                voice=voice,
                out_path=out_path,
            )
            scene_duration = audio_duration + _TAIL_PAD_SECONDS
            duration_map[scene.id] = scene_duration

            # Sub-progress for narration
            sub_pct = 25 + (25 * (i + 1) / total_scenes)
            self._emit(
                ProgressEvent(
                    stage="narrating",
                    pct=sub_pct,
                    message=f"Narrated scene {i + 1}/{total_scenes}",
                )
            )

        return duration_map

    def _stage_rendering(
        self,
        script: Script,
        duration_map: dict[int, float],
        fps: int,
        resolution: str,
        work_dir: Path,
    ) -> None:
        """Stage 3: Render frames for all scenes."""
        # Sanitize scene data before rendering
        self._sanitize_script_data(script)

        # Discover templates
        registry = Registry()
        registry.discover()

        # Build render jobs
        frames_dir = work_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        jobs: list[SceneRenderJob] = []
        for scene in script.scenes:
            template = registry.get_template(scene.kind)
            scene_frames_dir = frames_dir / f"s{scene.id}"
            scene_frames_dir.mkdir(parents=True, exist_ok=True)

            # The scene heading lives on Scene.title, but templates read it from
            # the data object passed to setSceneData(). Merge it in, letting an
            # explicit data["title"] win if a script provides one.
            scene_data = dict(scene.data)
            scene_data.setdefault("title", scene.title)

            jobs.append(
                SceneRenderJob(
                    scene_id=scene.id,
                    template_html=template.index_html,
                    data=scene_data,
                    style=template.default_style,
                    duration=duration_map[scene.id],
                    frames_dir=scene_frames_dir,
                )
            )

        # Render all scenes
        renderer = Renderer(fps=fps, resolution=resolution)
        total_scenes = len(jobs)

        # Emit sub-progress per scene (approximate since render_all is batch)
        for i in range(total_scenes):
            sub_pct = 50 + (25 * i / total_scenes)
            self._emit(
                ProgressEvent(
                    stage="rendering",
                    pct=sub_pct,
                    message=f"Rendering scene {i + 1}/{total_scenes}",
                )
            )

        renderer.render_all(jobs, work_dir)

        self._emit(
            ProgressEvent(
                stage="rendering",
                pct=75,
                message=f"Rendered {total_scenes} scenes",
            )
        )

    def _stage_composing(
        self,
        script: Script,
        duration_map: dict[int, float],
        fps: int,
        resolution: str,
        music: str | None,
        work_dir: Path,
        output_path: Path,
    ) -> Path:
        """Stage 4: Compose final video from frames + audio."""
        audio_dir = work_dir / "audio"
        frames_dir = work_dir / "frames"

        # Build composition jobs
        comp_jobs: list[CompositionJob] = []
        for scene in script.scenes:
            comp_jobs.append(
                CompositionJob(
                    scene_id=scene.id,
                    frames_dir=frames_dir / f"s{scene.id}",
                    audio_path=audio_dir / f"scene{scene.id}.mp3",
                )
            )

        composer = Composer(fps=fps, resolution=resolution)
        music_path = Path(music) if music else None

        # Compose to work_dir/output.mp4
        work_output = work_dir / "output.mp4"
        composer.compose(comp_jobs, work_dir, work_output, music=music_path)

        # Copy to final output location
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(work_output, output_path)

        self._emit(
            ProgressEvent(stage="composing", pct=100, message="Composition complete")
        )

        return output_path

    # ------------------------------------------------------------------
    # Shared execution path (stages 2-4)
    # ------------------------------------------------------------------

    def _execute_from_narration(
        self,
        script: Script,
        fps: int,
        resolution: str,
        music: str | None,
        out: str | None,
        keep_artifacts: bool,
        work_dir: Path,
        topic: str,
    ) -> GenerateResult:
        """Execute narration, rendering, and composition stages."""
        # Shared by generate() and render()/--script: reject unsafe animation
        # code before spending TTS or Chromium time on it.
        self._validate_animation_scenes(script)

        # Stage 2: Narration
        self._emit(
            ProgressEvent(stage="narrating", pct=25, message="Starting narration...")
        )
        duration_map = self._stage_narrating(script, work_dir)

        # Stage 3: Rendering
        self._emit(
            ProgressEvent(stage="rendering", pct=50, message="Starting rendering...")
        )
        self._stage_rendering(script, duration_map, fps, resolution, work_dir)

        # Stage 4: Composition
        self._emit(
            ProgressEvent(stage="composing", pct=75, message="Composing video...")
        )
        output_path = _resolve_output_path(topic, out)
        final_path = self._stage_composing(
            script, duration_map, fps, resolution, music, work_dir, output_path
        )

        # Done
        self._emit(
            ProgressEvent(stage="done", pct=100, message="Video generation complete")
        )

        # Cleanup
        if not keep_artifacts:
            self._cleanup(work_dir)

        return GenerateResult(
            mp4_path=final_path,
            script=script,
            work_dir=work_dir,
        )

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _emit(self, event: ProgressEvent) -> None:
        """Emit a progress event via the callback, if configured."""
        if self.on_progress is not None:
            try:
                self.on_progress(event)
            except Exception:
                logger.debug("on_progress callback raised; ignoring", exc_info=True)

    @staticmethod
    def _validate_animation_scenes(script: Script) -> None:
        """Reject animation scenes whose code is unsafe or non-reproducible.

        Raises:
            ScriptValidationError: If any animation scene fails validation.
        """
        violations: list[str] = []
        for scene in script.scenes:
            if scene.kind == SceneKind.ANIMATION:
                violations.extend(
                    f"scene {scene.id} ({scene.title}): {issue}"
                    for issue in validate_animation_code(scene.data)
                )
        if violations:
            raise ScriptValidationError(
                "Model-authored animation code is not reproducible:\n  "
                + "\n  ".join(violations)
            )

    @staticmethod
    def _sanitize_script_data(script: Script) -> None:
        """Sanitize all scene data in a Script before rendering.

        Mutates scene.data and scene.title in place with sanitized values.
        Both come from the LLM and are injected into the DOM, so both are
        untrusted.
        """
        for scene in script.scenes:
            if scene.kind == SceneKind.ANIMATION:
                # Keep HTML/SVG tags in markup (they are the stage), but strip
                # handlers / javascript: / data: threats. css/js stay intact
                # for draw(t); validate_animation_code() already gated them.
                code: dict[str, Any] = {}
                for key, value in scene.data.items():
                    if key not in ANIMATION_CODE_FIELDS:
                        continue
                    if key == "markup" and isinstance(value, str):
                        code[key] = sanitize_animation_markup(value)
                    else:
                        code[key] = value
                rest = {
                    key: value
                    for key, value in scene.data.items()
                    if key not in ANIMATION_CODE_FIELDS
                }
                scene.data = {**sanitize_scene_data(rest), **code}
            else:
                scene.data = sanitize_scene_data(scene.data)
            scene.title = sanitize_scene_data(scene.title)

    @staticmethod
    def _cleanup(work_dir: Path) -> None:
        """Remove the work directory, ignoring errors."""
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except Exception:
            logger.debug("Failed to clean up work_dir: %s", work_dir, exc_info=True)


__all__ = ["GenerateResult", "Pipeline", "ProgressEvent", "_slugify"]
