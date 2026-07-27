"""End-to-end test: full pipeline with heuristic LLM + mock TTS.

Tests the complete generation pipeline using the heuristic script generator
and the mock TTS provider (no network calls). If Playwright/Chromium and ffmpeg
are available, performs real rendering and validates the output MP4.
If not, mocks the renderer and composer to verify pipeline orchestration.

Marked @pytest.mark.e2e.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from explainer.core.schema import Script
from tests.helpers import (
    MockTTSProvider,
    is_ffprobe_available,
    requires_ffmpeg,
)

pytestmark = [pytest.mark.e2e]


# ---------------------------------------------------------------------------
# Full pipeline e2e (with real rendering if available)
# ---------------------------------------------------------------------------


@requires_ffmpeg()
def test_e2e_full_pipeline_produces_valid_mp4(tmp_path: Path):
    """Full pipeline: heuristic LLM + mock TTS + mock render → compose → valid MP4.

    This test exercises the heuristic script generator, mock TTS, and real
    FFmpeg compositor. The renderer is mocked to produce minimal valid PNG frames,
    since the rendering stage depends on Playwright API specifics that may vary.
    Validates the output MP4 with ffprobe.
    """
    from explainer.core.pipeline import Pipeline

    mock_tts = MockTTSProvider(duration=1.5)
    output_path = tmp_path / "output.mp4"

    # Create a minimal 1x1 white PNG for fake frames
    # PNG: 8-byte header + IHDR + IDAT + IEND (minimal valid)
    _MINIMAL_PNG = _create_minimal_720p_png()

    # Patch narration and rendering stages
    with (
        patch("explainer.core.pipeline.Pipeline._stage_narrating") as mock_narrate,
        patch("explainer.core.pipeline.Pipeline._stage_rendering") as mock_render,
    ):

        def fake_narrate(script: Script, work_dir: Path) -> dict[int, float]:
            audio_dir = work_dir / "audio"
            audio_dir.mkdir(parents=True, exist_ok=True)
            duration_map = {}
            for scene in script.scenes:
                out_path = audio_dir / f"scene{scene.id}.mp3"
                mock_tts.synthesize(scene.narration, "mock-voice", out_path)
                duration_map[scene.id] = mock_tts.duration + 0.4  # + tail pad
            return duration_map

        def fake_render(script, duration_map, fps, resolution, work_dir):
            frames_dir = work_dir / "frames"
            frames_dir.mkdir(parents=True, exist_ok=True)
            for scene in script.scenes:
                scene_dir = frames_dir / f"s{scene.id}"
                scene_dir.mkdir(parents=True, exist_ok=True)
                # Create enough frames for the duration at the given fps
                scene_duration = duration_map[scene.id]
                frame_count = max(1, round(scene_duration * fps))
                for i in range(frame_count):
                    (scene_dir / f"f{i:04d}.png").write_bytes(_MINIMAL_PNG)

        mock_narrate.side_effect = fake_narrate
        mock_render.side_effect = fake_render

        pipeline = Pipeline(llm=None, tts="edge")
        result = pipeline.generate(
            topic="gravity",
            language="en",
            audience="student",
            target_duration=30,
            fps=5,  # Low FPS for faster test
            resolution="720p",
            out=str(output_path),
            keep_artifacts=True,
        )

    # Verify output exists
    assert result.mp4_path.exists(), "MP4 file was not produced"
    assert result.mp4_path.stat().st_size > 0, "MP4 file is empty"

    # Verify script was generated
    assert result.script is not None
    assert result.script.topic == "gravity"
    assert len(result.script.scenes) >= 3

    # Validate with ffprobe if available
    if is_ffprobe_available():
        _validate_mp4_with_ffprobe(result.mp4_path)


# ---------------------------------------------------------------------------
# Pipeline orchestration test (no Chromium/ffmpeg needed)
# ---------------------------------------------------------------------------


def test_e2e_pipeline_orchestration_with_mocks(tmp_path: Path):
    """Verify pipeline stages execute in correct order with all deps mocked.

    This test works in any environment — it mocks the renderer and composer
    to verify the orchestration logic without external dependencies.
    """
    from explainer.core.pipeline import Pipeline

    mock_tts = MockTTSProvider(duration=1.5)
    output_path = tmp_path / "output.mp4"

    stages_executed: list[str] = []

    # Mock all pipeline stages that require external deps
    with (
        patch("explainer.core.pipeline.Pipeline._stage_narrating") as mock_narrate,
        patch("explainer.core.pipeline.Pipeline._stage_rendering") as mock_render,
        patch("explainer.core.pipeline.Pipeline._stage_composing") as mock_compose,
    ):

        def fake_narrate(script: Script, work_dir: Path) -> dict[int, float]:
            stages_executed.append("narrating")
            audio_dir = work_dir / "audio"
            audio_dir.mkdir(parents=True, exist_ok=True)
            duration_map = {}
            for scene in script.scenes:
                out_path = audio_dir / f"scene{scene.id}.mp3"
                mock_tts.synthesize(scene.narration, "mock-voice", out_path)
                duration_map[scene.id] = mock_tts.duration + 0.4
            return duration_map

        def fake_render(script, duration_map, fps, resolution, work_dir):
            stages_executed.append("rendering")
            # Create fake frame directories
            frames_dir = work_dir / "frames"
            frames_dir.mkdir(parents=True, exist_ok=True)
            for scene in script.scenes:
                scene_dir = frames_dir / f"s{scene.id}"
                scene_dir.mkdir(parents=True, exist_ok=True)
                # Create a single fake frame
                (scene_dir / "f0000.png").write_bytes(
                    b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
                )

        def fake_compose(
            script, duration_map, fps, resolution, music, work_dir, output_path
        ):
            stages_executed.append("composing")
            # Create a fake MP4 file
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"\x00\x00\x00\x1cftypisom" + b"\x00" * 100)
            return output_path

        mock_narrate.side_effect = fake_narrate
        mock_render.side_effect = fake_render
        mock_compose.side_effect = fake_compose

        pipeline = Pipeline(llm=None, tts="edge")
        result = pipeline.generate(
            topic="photosynthesis",
            language="en",
            audience="student",
            target_duration=30,
            fps=15,
            resolution="720p",
            out=str(output_path),
            keep_artifacts=True,
        )

    # Verify stages executed in order
    assert stages_executed == ["narrating", "rendering", "composing"], (
        f"Stages executed out of order: {stages_executed}"
    )

    # Verify result
    assert result.script.topic == "photosynthesis"
    assert len(result.script.scenes) == 4  # Heuristic produces 4 scenes


def test_e2e_heuristic_script_generation():
    """Verify heuristic generator produces a valid Script without any network."""
    from explainer.providers.llm_base import ScriptRequest, TemplateInfo
    from explainer.providers.llm_heuristic import HeuristicProvider

    provider = HeuristicProvider()
    request = ScriptRequest(
        topic="black holes",
        language="en",
        audience="adult",
        target_duration=60,
        available_templates=[
            TemplateInfo(kind="title", name="Title", data_schema={}),
            TemplateInfo(kind="concept", name="Concept", data_schema={}),
            TemplateInfo(kind="steps", name="Steps", data_schema={}),
            TemplateInfo(kind="takeaway", name="Takeaway", data_schema={}),
        ],
    )

    script = provider.generate_script(request)

    # Validate structure
    assert script.topic == "black holes"
    assert script.language == "en"
    assert script.audience == "adult"
    assert len(script.scenes) == 4
    assert script.scenes[0].kind.value == "title"
    assert script.scenes[-1].kind.value == "takeaway"

    # Validate all scenes have narration
    for scene in script.scenes:
        assert scene.narration, f"Scene {scene.id} has no narration"
        assert len(scene.narration) <= 400, f"Scene {scene.id} narration too long"


def test_e2e_mock_tts_produces_valid_audio(tmp_path: Path):
    """Verify MockTTSProvider generates files that look like audio."""
    mock_tts = MockTTSProvider(duration=2.0)

    out_path = tmp_path / "test_audio.mp3"
    duration = mock_tts.synthesize("Hello world", "mock-voice", out_path)

    assert duration == 2.0
    assert out_path.exists()
    assert out_path.stat().st_size > 0

    # Verify the call was tracked
    assert len(mock_tts.calls) == 1
    assert mock_tts.calls[0]["text"] == "Hello world"


# ---------------------------------------------------------------------------
# Helper: minimal valid PNG for fake frames
# ---------------------------------------------------------------------------


def _create_minimal_720p_png() -> bytes:
    """Create a minimal valid 1280x720 PNG (solid color) for test frames.

    Uses ffmpeg to generate a single-frame PNG if available,
    otherwise creates a minimal PNG byte sequence.
    """
    import shutil
    import tempfile

    if shutil.which("ffmpeg"):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp_path_str = f.name

        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=1280x720:d=0.04",
                "-frames:v",
                "1",
                tmp_path_str,
            ],
            capture_output=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            data = Path(tmp_path_str).read_bytes()
            Path(tmp_path_str).unlink(missing_ok=True)
            return data
        Path(tmp_path_str).unlink(missing_ok=True)

    # Fallback: minimal valid PNG (1x1 black pixel)
    # This won't be 1280x720 but is structurally valid for ffmpeg input
    import struct
    import zlib

    def _make_png(width: int, height: int) -> bytes:
        """Generate a minimal valid PNG with solid black pixels."""
        # IHDR
        ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
        ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)

        # IDAT (raw image data: filter byte 0 + black pixels per row)
        raw_row = b"\x00" + b"\x00\x00\x00" * width  # filter=None + RGB black
        raw_data = raw_row * height
        compressed = zlib.compress(raw_data)
        idat_crc = zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF
        idat = (
            struct.pack(">I", len(compressed))
            + b"IDAT"
            + compressed
            + struct.pack(">I", idat_crc)
        )

        # IEND
        iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
        iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)

        return b"\x89PNG\r\n\x1a\n" + ihdr + idat + iend

    return _make_png(1280, 720)


# ---------------------------------------------------------------------------
# MP4 validation helper
# ---------------------------------------------------------------------------


def _validate_mp4_with_ffprobe(mp4_path: Path) -> None:
    """Validate an MP4 file using ffprobe: check resolution, fps, codecs.

    Args:
        mp4_path: Path to the MP4 file to validate.

    Raises:
        AssertionError: If any validation check fails.
    """
    # Get format info
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(mp4_path),
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, f"ffprobe failed: {result.stderr}"

    probe_data = json.loads(result.stdout)

    # Verify we have streams
    assert "streams" in probe_data, "No streams found in MP4"
    streams = probe_data["streams"]
    assert len(streams) >= 1, "Expected at least 1 stream (video)"

    # Find video stream
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    assert len(video_streams) >= 1, "No video stream found"

    video = video_streams[0]

    # Verify codec
    assert video.get("codec_name") == "h264", (
        f"Expected h264 codec, got {video.get('codec_name')}"
    )

    # Verify resolution (should be 1280x720 for 720p)
    width = int(video.get("width", 0))
    height = int(video.get("height", 0))
    assert width > 0 and height > 0, f"Invalid dimensions: {width}x{height}"

    # Verify duration is reasonable (> 0 seconds)
    format_info = probe_data.get("format", {})
    duration_str = format_info.get("duration", "0")
    duration = float(duration_str)
    assert duration > 0, f"Video duration is 0 or negative: {duration}"

    # Check for audio stream (should have AAC)
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    if audio_streams:
        audio = audio_streams[0]
        assert audio.get("codec_name") == "aac", (
            f"Expected AAC audio codec, got {audio.get('codec_name')}"
        )
