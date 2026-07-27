"""Unit tests for explainer.core.renderer — SceneRenderJob, Renderer, resolution parsing.

These tests validate dataclass creation, resolution parsing, frame count
calculation, and crash-resume logic WITHOUT requiring Playwright/Chromium.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from explainer.core.renderer import Renderer, SceneRenderJob, _parse_resolution

# ---------------------------------------------------------------------------
# SceneRenderJob dataclass
# ---------------------------------------------------------------------------


class TestSceneRenderJob:
    def test_creation_minimal(self, tmp_path: Path):
        job = SceneRenderJob(
            scene_id=1,
            template_html=Path("/templates/title/index.html"),
            data={"bullets": ["a", "b"]},
            style={"bg": "#000", "accent": "#fff"},
            duration=5.0,
            frames_dir=tmp_path / "frames" / "s1",
        )
        assert job.scene_id == 1
        assert job.template_html == Path("/templates/title/index.html")
        assert job.data == {"bullets": ["a", "b"]}
        assert job.style == {"bg": "#000", "accent": "#fff"}
        assert job.duration == 5.0
        assert job.frames_dir == tmp_path / "frames" / "s1"

    def test_creation_empty_data(self, tmp_path: Path):
        job = SceneRenderJob(
            scene_id=3,
            template_html=Path("/t/index.html"),
            data={},
            style={},
            duration=2.5,
            frames_dir=tmp_path / "s3",
        )
        assert job.data == {}
        assert job.style == {}

    def test_creation_with_nested_data(self, tmp_path: Path):
        data = {
            "title": "Photosynthesis",
            "bullets": ["light", "water", "CO2"],
            "diagram": {"type": "cycle", "labels": ["input", "output"]},
        }
        job = SceneRenderJob(
            scene_id=2,
            template_html=Path("/t/concept/index.html"),
            data=data,
            style={"bg": "#0d1b2a", "accent": "#4fc3f7"},
            duration=10.0,
            frames_dir=tmp_path / "s2",
        )
        assert job.data["diagram"]["type"] == "cycle"
        assert len(job.data["bullets"]) == 3


# ---------------------------------------------------------------------------
# Resolution parsing
# ---------------------------------------------------------------------------


class TestResolutionParsing:
    def test_720p(self):
        assert _parse_resolution("720p") == (1280, 720)

    def test_1080p(self):
        assert _parse_resolution("1080p") == (1920, 1080)

    def test_vertical(self):
        assert _parse_resolution("vertical") == (720, 1280)

    def test_case_insensitive(self):
        assert _parse_resolution("720P") == (1280, 720)
        assert _parse_resolution("1080P") == (1920, 1080)
        assert _parse_resolution("VERTICAL") == (720, 1280)

    def test_with_whitespace(self):
        assert _parse_resolution("  720p  ") == (1280, 720)

    def test_explicit_wxh(self):
        assert _parse_resolution("1920x1080") == (1920, 1080)
        assert _parse_resolution("800x600") == (800, 600)

    def test_unknown_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown resolution"):
            _parse_resolution("4k")

    def test_invalid_wxh_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown resolution"):
            _parse_resolution("abcxdef")

    def test_renderer_stores_parsed_resolution(self):
        r = Renderer(fps=15, resolution="1080p")
        assert r.width == 1920
        assert r.height == 1080


# ---------------------------------------------------------------------------
# Frame count calculation
# ---------------------------------------------------------------------------


class TestFrameCount:
    def test_standard_15fps(self):
        r = Renderer(fps=15)
        # 5 seconds * 15 fps = 75 frames
        assert r._frame_count(5.0) == 75

    def test_standard_24fps(self):
        r = Renderer(fps=24)
        # 2.5 seconds * 24 fps = 60 frames
        assert r._frame_count(2.5) == 60

    def test_standard_30fps(self):
        r = Renderer(fps=30)
        # 1 second * 30 fps = 30 frames
        assert r._frame_count(1.0) == 30

    def test_fractional_duration_rounds(self):
        r = Renderer(fps=15)
        # 1.1 seconds * 15 fps = 16.5 → rounds to 16
        assert r._frame_count(1.1) == 16
        # 1.2 seconds * 15 fps = 18 → exactly 18
        assert r._frame_count(1.2) == 18

    def test_very_short_duration_minimum_1_frame(self):
        r = Renderer(fps=15)
        # Very short duration should still produce at least 1 frame
        assert r._frame_count(0.01) == 1
        assert r._frame_count(0.0) == 1

    def test_zero_duration(self):
        r = Renderer(fps=15)
        assert r._frame_count(0.0) >= 1


# ---------------------------------------------------------------------------
# Renderer initialization
# ---------------------------------------------------------------------------


class TestRendererInit:
    def test_defaults(self):
        r = Renderer()
        assert r.fps == 15
        assert r.resolution == "720p"
        assert r.width == 1280
        assert r.height == 720
        assert r.resume is False
        assert r.workers >= 1
        assert r.workers <= 4

    def test_custom_workers(self):
        r = Renderer(workers=2)
        assert r.workers == 2

    def test_resume_flag(self):
        r = Renderer(resume=True)
        assert r.resume is True

    def test_custom_fps(self):
        r = Renderer(fps=30)
        assert r.fps == 30

    def test_invalid_resolution_raises(self):
        with pytest.raises(ValueError):
            Renderer(resolution="invalid")


# ---------------------------------------------------------------------------
# Crash-resume logic
# ---------------------------------------------------------------------------


class TestCrashResume:
    def test_scene_complete_with_all_frames(self, tmp_path: Path):
        r = Renderer(fps=15, resume=True)
        frames_dir = tmp_path / "s1"
        frames_dir.mkdir()
        # Create 75 fake frame files
        for i in range(75):
            (frames_dir / f"f{i:04d}.png").write_bytes(b"fake")
        assert r._scene_complete(frames_dir, 75) is True

    def test_scene_incomplete_missing_frames(self, tmp_path: Path):
        r = Renderer(fps=15, resume=True)
        frames_dir = tmp_path / "s1"
        frames_dir.mkdir()
        # Only create 50 of 75 expected frames
        for i in range(50):
            (frames_dir / f"f{i:04d}.png").write_bytes(b"fake")
        assert r._scene_complete(frames_dir, 75) is False

    def test_scene_complete_nonexistent_dir(self, tmp_path: Path):
        r = Renderer(fps=15, resume=True)
        frames_dir = tmp_path / "nonexistent"
        assert r._scene_complete(frames_dir, 75) is False

    def test_scene_complete_extra_frames_ok(self, tmp_path: Path):
        r = Renderer(fps=15, resume=True)
        frames_dir = tmp_path / "s1"
        frames_dir.mkdir()
        # More frames than expected is still complete
        for i in range(80):
            (frames_dir / f"f{i:04d}.png").write_bytes(b"fake")
        assert r._scene_complete(frames_dir, 75) is True

    def test_render_all_empty_list(self, tmp_path: Path):
        """render_all with empty list should not raise."""
        r = Renderer(fps=15)
        r.render_all([], tmp_path)
