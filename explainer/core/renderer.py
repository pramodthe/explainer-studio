"""Headless Chromium frame renderer with parallel scene support.

Renders each scene by loading its template HTML in a Playwright-controlled
Chromium instance, stepping progress t from 0→1, and capturing PNG frames.
Scenes are rendered in parallel via ProcessPoolExecutor.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Route, ViewportSize, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from explainer.core.errors import RenderError

logger = logging.getLogger(__name__)

# Playwright's page.evaluate() accepts no per-call timeout. This page-level
# default bounds navigation and screenshot operations instead.
_PAGE_TIMEOUT_MS = 5000

# Templates lay themselves out on a fixed stage of this size by convention.
# Higher resolutions are produced by scaling the device pixel ratio rather than
# by enlarging the viewport, which would leave the stage in the top-left corner.
_STAGE_WIDTH = 1280
_STAGE_HEIGHT = 720

# ---------------------------------------------------------------------------
# Resolution presets
# ---------------------------------------------------------------------------

_RESOLUTION_MAP: dict[str, tuple[int, int]] = {
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "vertical": (720, 1280),
}


def _parse_resolution(resolution: str) -> tuple[int, int]:
    """Parse a resolution string into (width, height).

    Supports presets: "720p", "1080p", "vertical".
    Also supports explicit "WxH" format (e.g. "1920x1080").

    Raises:
        ValueError: If the resolution string is not recognized.
    """
    key = resolution.lower().strip()
    if key in _RESOLUTION_MAP:
        return _RESOLUTION_MAP[key]
    # Try WxH format
    if "x" in key:
        parts = key.split("x", 1)
        try:
            return (int(parts[0]), int(parts[1]))
        except ValueError:
            pass
    raise ValueError(
        f"Unknown resolution '{resolution}'. "
        f"Use one of {list(_RESOLUTION_MAP.keys())} or 'WxH' format."
    )


# ---------------------------------------------------------------------------
# SceneRenderJob
# ---------------------------------------------------------------------------


@dataclass
class SceneRenderJob:
    """Describes a single scene to render.

    Attributes:
        scene_id: Unique identifier for the scene.
        template_html: Path to the template's index.html file.
        data: Scene data dict to pass to window.setSceneData.
        style: Style dict to pass to window.setSceneData.
        duration: Scene duration in seconds (determines frame count).
        frames_dir: Output directory for frame PNGs.
    """

    scene_id: int
    template_html: Path
    data: dict[str, Any]
    style: dict[str, Any]
    duration: float
    frames_dir: Path


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


class Renderer:
    """Parallel scene renderer using headless Chromium via Playwright.

    Each scene is rendered in its own Chromium process for isolation.
    Parallelism is at the scene level via ProcessPoolExecutor.
    """

    def __init__(
        self,
        fps: int = 15,
        resolution: str = "720p",
        workers: int | None = None,
        resume: bool = False,
    ) -> None:
        """Initialize the renderer.

        Args:
            fps: Frames per second for rendering (default 15).
            resolution: Output resolution preset or WxH string.
            workers: Number of parallel workers. Defaults to min(4, cpu_count).
            resume: If True, skip scenes whose frames_dir already contains
                    the expected number of frames.
        """
        self.fps = fps
        self.resolution = resolution
        self.width, self.height = _parse_resolution(resolution)
        self.workers = workers if workers is not None else min(4, os.cpu_count() or 1)
        self.resume = resume

    def _frame_count(self, duration: float) -> int:
        """Compute the number of frames for a given duration."""
        return max(1, round(duration * self.fps))

    def _viewport_and_scale(self) -> tuple[ViewportSize, float]:
        """Choose a viewport and device pixel ratio for the target resolution.

        Templates render onto a fixed 1280x720 stage. Enlarging the viewport
        would place that stage in the top-left corner of a bigger canvas, so
        when the target shares the stage's aspect ratio the stage is kept at
        its native size and the device pixel ratio is scaled instead. Screenshots
        then come out at exactly the requested pixel dimensions, full-bleed.

        Returns:
            A (viewport, device_scale_factor) pair.
        """
        scale = self.width / _STAGE_WIDTH
        matches_aspect = abs(self.height - _STAGE_HEIGHT * scale) < 1.0

        if matches_aspect:
            return {"width": _STAGE_WIDTH, "height": _STAGE_HEIGHT}, scale

        # Aspect ratio differs from the stage (e.g. "vertical"). Bundled
        # templates have no layout for this, so render at the requested size
        # and let the template decide — but say so rather than failing quietly.
        logger.warning(
            "Resolution %dx%d does not match the %dx%d template stage aspect "
            "ratio; bundled templates will not fill the frame.",
            self.width,
            self.height,
            _STAGE_WIDTH,
            _STAGE_HEIGHT,
        )
        return {"width": self.width, "height": self.height}, 1.0

    def render_all(self, scenes: list[SceneRenderJob], work_dir: Path) -> None:
        """Render all scenes in parallel using ProcessPoolExecutor.

        Args:
            scenes: List of SceneRenderJob objects to render.
            work_dir: Base work directory (used for context/logging).

        Raises:
            RenderError: If any scene fails to render.
        """
        if not scenes:
            return

        # For a single scene or single worker, render sequentially
        if len(scenes) == 1 or self.workers <= 1:
            for job in scenes:
                self._render_scene(job, work_dir)
            return

        # Parallel rendering
        with ProcessPoolExecutor(max_workers=self.workers) as executor:
            futures = {
                executor.submit(self._render_scene, job, work_dir): job
                for job in scenes
            }
            for future in futures:
                # Re-raise any exception from the worker
                future.result()

    def _render_scene(self, job: SceneRenderJob, work_dir: Path) -> None:
        """Render a single scene's frames.

        Launches Playwright with Chromium, blocks non-file:// network access,
        loads the template HTML, injects scene data, and captures frames.

        Args:
            job: The SceneRenderJob describing what to render.
            work_dir: Base work directory.

        Raises:
            RenderError: On JS errors, timeouts, or Chromium crashes.
        """
        frame_count = self._frame_count(job.duration)

        # Crash-resume: skip if frames already exist
        if self.resume and self._scene_complete(job.frames_dir, frame_count):
            logger.info(
                f"Scene {job.scene_id}: skipping (resume=True, "
                f"{frame_count} frames already exist)"
            )
            return

        # Ensure output directory exists
        job.frames_dir.mkdir(parents=True, exist_ok=True)

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                try:
                    viewport, scale = self._viewport_and_scale()
                    page = browser.new_page(
                        viewport=viewport, device_scale_factor=scale
                    )
                    page.set_default_timeout(_PAGE_TIMEOUT_MS)

                    # Block all non-file:// network requests for security
                    # and determinism
                    def _route_handler(route: Route) -> None:
                        if route.request.url.startswith("file://"):
                            route.continue_()
                        else:
                            route.abort()

                    page.route("**/*", _route_handler)

                    # Load template HTML via file:// URL
                    template_url = f"file://{job.template_html.resolve()}"
                    page.goto(template_url)

                    # Inject scene data
                    try:
                        page.evaluate(
                            "([data, style]) => window.setSceneData(data, style)",
                            [job.data, job.style],
                        )
                    except PlaywrightTimeoutError as exc:
                        raise RenderError(
                            f"setSceneData timed out ({_PAGE_TIMEOUT_MS}ms limit)",
                            scene_id=job.scene_id,
                            frame_index=None,
                        ) from exc
                    except PlaywrightError as exc:
                        raise RenderError(
                            f"setSceneData failed: {exc}",
                            scene_id=job.scene_id,
                            frame_index=None,
                        ) from exc

                    # Render frames by stepping t from 0 to 1
                    for i in range(frame_count):
                        t = i / (frame_count - 1) if frame_count > 1 else 1.0
                        try:
                            page.evaluate("(t) => window.renderFrame(t)", t)
                        except PlaywrightTimeoutError as exc:
                            raise RenderError(
                                f"renderFrame timed out at frame {i} "
                                f"({_PAGE_TIMEOUT_MS}ms limit)",
                                scene_id=job.scene_id,
                                frame_index=i,
                            ) from exc
                        except PlaywrightError as exc:
                            raise RenderError(
                                f"renderFrame failed at t={t:.4f}: {exc}",
                                scene_id=job.scene_id,
                                frame_index=i,
                            ) from exc

                        frame_path = job.frames_dir / f"f{i:04d}.png"
                        page.screenshot(path=str(frame_path))

                    logger.info(
                        f"Scene {job.scene_id}: rendered {frame_count} frames "
                        f"({job.duration:.1f}s at {self.fps}fps)"
                    )
                finally:
                    browser.close()

        except RenderError:
            raise
        except PlaywrightError as exc:
            # Chromium crash or other Playwright-level failure
            raise RenderError(
                f"Chromium crashed: {exc}",
                scene_id=job.scene_id,
            ) from exc
        except Exception as exc:
            raise RenderError(
                f"Unexpected rendering failure: {exc}",
                scene_id=job.scene_id,
            ) from exc

    def _scene_complete(self, frames_dir: Path, expected_count: int) -> bool:
        """Check if a scene's frame directory already has all expected frames.

        Args:
            frames_dir: Path to the frames directory.
            expected_count: Number of frames expected.

        Returns:
            True if the directory exists and contains the expected number
            of PNG files.
        """
        if not frames_dir.exists():
            return False
        existing = list(frames_dir.glob("f*.png"))
        return len(existing) >= expected_count


__all__ = [
    "Renderer",
    "SceneRenderJob",
    "_parse_resolution",
]
