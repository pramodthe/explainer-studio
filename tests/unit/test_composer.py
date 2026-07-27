"""Unit tests for explainer.core.composer module."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from explainer.core.composer import Composer, CompositionJob
from explainer.core.errors import CompositionError


class TestCompositionJob:
    """Tests for the CompositionJob dataclass."""

    def test_creation(self, tmp_path: Path) -> None:
        frames_dir = tmp_path / "frames" / "s1"
        audio_path = tmp_path / "audio" / "scene1.mp3"

        job = CompositionJob(scene_id=1, frames_dir=frames_dir, audio_path=audio_path)

        assert job.scene_id == 1
        assert job.frames_dir == frames_dir
        assert job.audio_path == audio_path

    def test_multiple_jobs_ordering(self, tmp_path: Path) -> None:
        jobs = [
            CompositionJob(
                scene_id=i,
                frames_dir=tmp_path / f"s{i}",
                audio_path=tmp_path / f"scene{i}.mp3",
            )
            for i in range(1, 4)
        ]

        assert [j.scene_id for j in jobs] == [1, 2, 3]


class TestComposerInit:
    """Tests for Composer initialization."""

    def test_init_stores_fps_and_resolution(self) -> None:
        composer = Composer(fps=15, resolution="720p")

        assert composer.fps == 15
        assert composer.resolution == "720p"

    def test_init_custom_values(self) -> None:
        composer = Composer(fps=30, resolution="1080p")

        assert composer.fps == 30
        assert composer.resolution == "1080p"


class TestConcatFileGeneration:
    """Tests for concat.txt generation within the compose method."""

    @patch("explainer.core.composer.subprocess.run")
    def test_concat_file_written_correctly(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Verify concat.txt is written with correct segment file paths."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )

        work_dir = tmp_path / "work"
        work_dir.mkdir()
        out_path = tmp_path / "output.mp4"

        # Single scene: no transitions, so the concat-demuxer path is used.
        scenes = [
            CompositionJob(
                scene_id=1, frames_dir=tmp_path / "s1", audio_path=tmp_path / "a1.mp3"
            ),
        ]

        composer = Composer(fps=15, resolution="720p")
        composer.compose(scenes, work_dir, out_path)

        concat_file = work_dir / "concat.txt"
        assert concat_file.exists()

        content = concat_file.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 1

        segments_dir = work_dir / "segments"
        assert lines[0] == f"file '{segments_dir / 'seg1.mp4'}'"

    @patch("explainer.core.composer.subprocess.run")
    def test_segments_dir_created(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Verify segments/ subdirectory is created in work_dir."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )

        work_dir = tmp_path / "work"
        work_dir.mkdir()
        out_path = tmp_path / "output.mp4"

        scenes = [
            CompositionJob(
                scene_id=1, frames_dir=tmp_path / "s1", audio_path=tmp_path / "a1.mp3"
            ),
        ]

        composer = Composer(fps=15, resolution="720p")
        composer.compose(scenes, work_dir, out_path)

        assert (work_dir / "segments").is_dir()


class TestFfmpegSubprocessCalls:
    """Tests that verify correct FFmpeg commands are constructed."""

    @patch("explainer.core.composer.subprocess.run")
    def test_encode_segment_command(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Verify per-scene FFmpeg encoding command has correct flags."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )

        work_dir = tmp_path / "work"
        work_dir.mkdir()
        out_path = tmp_path / "output.mp4"
        frames_dir = tmp_path / "s1"
        audio_path = tmp_path / "scene1.mp3"

        scenes = [
            CompositionJob(scene_id=1, frames_dir=frames_dir, audio_path=audio_path)
        ]

        composer = Composer(fps=15, resolution="720p")
        composer.compose(scenes, work_dir, out_path)

        # First call should be the segment encoding
        encode_call = mock_run.call_args_list[0]
        cmd = encode_call[0][0]

        assert cmd[0] == "ffmpeg"
        assert "-framerate" in cmd
        assert cmd[cmd.index("-framerate") + 1] == "15"
        assert "-i" in cmd
        assert str(frames_dir / "f%04d.png") in cmd
        assert str(audio_path) in cmd
        assert "-c:v" in cmd
        assert "libx264" in cmd
        assert "-pix_fmt" in cmd
        assert "yuv420p" in cmd
        assert "-c:a" in cmd
        assert "aac" in cmd
        # apad + shortest keeps the tail-pad silence: the audio is padded so
        # -shortest cuts on the (longer) frame track, not the narration MP3.
        assert cmd[cmd.index("-af") + 1] == "apad"
        assert "-shortest" in cmd
        assert "-map_metadata" in cmd
        assert "-1" in cmd

    @patch("explainer.core.composer.subprocess.run")
    def test_concat_command(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Verify the concat demuxer command has correct flags."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )

        work_dir = tmp_path / "work"
        work_dir.mkdir()
        out_path = tmp_path / "output.mp4"

        scenes = [
            CompositionJob(
                scene_id=1, frames_dir=tmp_path / "s1", audio_path=tmp_path / "a1.mp3"
            ),
        ]

        composer = Composer(fps=15, resolution="720p")
        composer.compose(scenes, work_dir, out_path)

        # Second call should be the concat
        concat_call = mock_run.call_args_list[1]
        cmd = concat_call[0][0]

        assert cmd[0] == "ffmpeg"
        assert "-f" in cmd
        assert cmd[cmd.index("-f") + 1] == "concat"
        assert "-safe" in cmd
        assert cmd[cmd.index("-safe") + 1] == "0"
        assert "-c" in cmd
        assert "copy" in cmd
        assert "-map_metadata" in cmd
        assert str(out_path) == cmd[-1]

    @patch("explainer.core.composer.subprocess.run")
    def test_music_ducking_command(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Verify amix filter command for music ducking."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )

        work_dir = tmp_path / "work"
        work_dir.mkdir()
        out_path = tmp_path / "output.mp4"
        music_path = tmp_path / "bgmusic.mp3"

        scenes = [
            CompositionJob(
                scene_id=1, frames_dir=tmp_path / "s1", audio_path=tmp_path / "a1.mp3"
            ),
        ]

        composer = Composer(fps=15, resolution="720p")
        composer.compose(scenes, work_dir, out_path, music=music_path)

        # Third call should be the music mixing
        music_call = mock_run.call_args_list[2]
        cmd = music_call[0][0]

        assert cmd[0] == "ffmpeg"
        assert "-filter_complex" in cmd
        filter_idx = cmd.index("-filter_complex")
        filter_val = cmd[filter_idx + 1]
        assert "volume=0.125" in filter_val
        assert "amix" in filter_val
        assert str(music_path) in cmd
        assert str(out_path) == cmd[-1]


class TestTransitionsJoin:
    """Tests for the xfade/acrossfade multi-scene join path."""

    def _three_scenes(self, tmp_path: Path) -> list[CompositionJob]:
        return [
            CompositionJob(
                scene_id=i,
                frames_dir=tmp_path / f"s{i}",
                audio_path=tmp_path / f"a{i}.mp3",
            )
            for i in range(1, 4)
        ]

    @patch.object(Composer, "_probe_duration", return_value=4.0)
    @patch("explainer.core.composer.subprocess.run")
    def test_xfade_filter_chain(
        self, mock_run: MagicMock, _mock_probe: MagicMock, tmp_path: Path
    ) -> None:
        """Multi-scene compose builds an xfade/acrossfade filter with right offsets."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )

        work_dir = tmp_path / "work"
        work_dir.mkdir()
        out_path = tmp_path / "output.mp4"

        composer = Composer(fps=15, resolution="720p")
        composer.compose(self._three_scenes(tmp_path), work_dir, out_path)

        # 3 segment encodes, then the join call
        join_call = mock_run.call_args_list[3]
        cmd = join_call[0][0]

        assert cmd[0] == "ffmpeg"
        filter_val = cmd[cmd.index("-filter_complex") + 1]
        # Durations of 4.0s each, fade 0.5s → offsets 3.5 and 7.0
        assert "xfade=transition=fade:duration=0.500:offset=3.500" in filter_val
        assert "xfade=transition=fade:duration=0.500:offset=7.000" in filter_val
        assert filter_val.count("acrossfade=d=0.500") == 2
        assert "[v2]" in cmd
        assert "[a2]" in cmd
        assert str(out_path) == cmd[-1]

    @patch.object(Composer, "_probe_duration", return_value=4.0)
    @patch("explainer.core.composer.subprocess.run")
    def test_no_concat_file_for_transitions(
        self, mock_run: MagicMock, _mock_probe: MagicMock, tmp_path: Path
    ) -> None:
        """The transition path does not write concat.txt."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )

        work_dir = tmp_path / "work"
        work_dir.mkdir()

        composer = Composer(fps=15, resolution="720p")
        composer.compose(
            self._three_scenes(tmp_path), work_dir, tmp_path / "output.mp4"
        )

        assert not (work_dir / "concat.txt").exists()

    @patch("explainer.core.composer.subprocess.run")
    def test_transition_zero_uses_concat_demuxer(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """transition=0 falls back to the concat demuxer with stream copy."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )

        work_dir = tmp_path / "work"
        work_dir.mkdir()

        composer = Composer(fps=15, resolution="720p", transition=0)
        composer.compose(
            self._three_scenes(tmp_path), work_dir, tmp_path / "output.mp4"
        )

        concat_call = mock_run.call_args_list[3]
        cmd = concat_call[0][0]
        assert cmd[cmd.index("-f") + 1] == "concat"
        assert "copy" in cmd
        assert (work_dir / "concat.txt").exists()

    @patch.object(Composer, "_probe_duration", return_value=0.8)
    @patch("explainer.core.composer.subprocess.run")
    def test_fade_clamped_to_half_shortest_scene(
        self, mock_run: MagicMock, _mock_probe: MagicMock, tmp_path: Path
    ) -> None:
        """The fade never exceeds half of the shortest segment."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )

        work_dir = tmp_path / "work"
        work_dir.mkdir()

        composer = Composer(fps=15, resolution="720p")
        composer.compose(
            self._three_scenes(tmp_path), work_dir, tmp_path / "output.mp4"
        )

        join_call = mock_run.call_args_list[3]
        filter_val = join_call[0][0][join_call[0][0].index("-filter_complex") + 1]
        # min(0.5, 0.8 / 2) = 0.4
        assert "duration=0.400" in filter_val
        assert "acrossfade=d=0.400" in filter_val

    @patch.object(Composer, "_probe_duration")
    @patch("explainer.core.composer.subprocess.run")
    def test_durations_arg_bypasses_ffprobe(
        self, mock_run: MagicMock, mock_probe: MagicMock, tmp_path: Path
    ) -> None:
        """Passing durations drives the offsets and skips ffprobe entirely."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        mock_probe.side_effect = AssertionError("_probe_duration must not be called")

        work_dir = tmp_path / "work"
        work_dir.mkdir()
        out_path = tmp_path / "output.mp4"

        composer = Composer(fps=15, resolution="720p")
        composer.compose(
            self._three_scenes(tmp_path),
            work_dir,
            out_path,
            durations=[4.0, 4.0, 4.0],
        )

        mock_probe.assert_not_called()
        join_call = mock_run.call_args_list[3]
        filter_val = join_call[0][0][join_call[0][0].index("-filter_complex") + 1]
        assert "xfade=transition=fade:duration=0.500:offset=3.500" in filter_val
        assert "xfade=transition=fade:duration=0.500:offset=7.000" in filter_val


class TestCompositionError:
    """Tests for error handling in Composer."""

    @patch("explainer.core.composer.subprocess.run")
    def test_raises_on_encode_failure(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """CompositionError raised when encoding fails."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="Error: invalid input"
        )

        work_dir = tmp_path / "work"
        work_dir.mkdir()
        out_path = tmp_path / "output.mp4"

        scenes = [
            CompositionJob(
                scene_id=1, frames_dir=tmp_path / "s1", audio_path=tmp_path / "a1.mp3"
            ),
        ]

        composer = Composer(fps=15, resolution="720p")

        with pytest.raises(CompositionError) as exc_info:
            composer.compose(scenes, work_dir, out_path)

        assert "encoding scene 1" in str(exc_info.value)
        assert exc_info.value.ffmpeg_stderr == "Error: invalid input"

    @patch("explainer.core.composer.subprocess.run")
    def test_raises_on_concat_failure(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """CompositionError raised when concat fails."""
        # First call (encode) succeeds, second call (concat) fails
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="concat error"
            ),
        ]

        work_dir = tmp_path / "work"
        work_dir.mkdir()
        out_path = tmp_path / "output.mp4"

        scenes = [
            CompositionJob(
                scene_id=1, frames_dir=tmp_path / "s1", audio_path=tmp_path / "a1.mp3"
            ),
        ]

        composer = Composer(fps=15, resolution="720p")

        with pytest.raises(CompositionError) as exc_info:
            composer.compose(scenes, work_dir, out_path)

        assert "concatenating" in str(exc_info.value)

    @patch("explainer.core.composer.subprocess.run")
    def test_stderr_truncated_to_1024_chars(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """FFmpeg stderr is truncated to 1024 characters in the exception."""
        long_stderr = "x" * 2000
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=long_stderr
        )

        work_dir = tmp_path / "work"
        work_dir.mkdir()
        out_path = tmp_path / "output.mp4"

        scenes = [
            CompositionJob(
                scene_id=1, frames_dir=tmp_path / "s1", audio_path=tmp_path / "a1.mp3"
            ),
        ]

        composer = Composer(fps=15, resolution="720p")

        with pytest.raises(CompositionError) as exc_info:
            composer.compose(scenes, work_dir, out_path)

        assert len(exc_info.value.ffmpeg_stderr) == 1024

    @patch("explainer.core.composer.subprocess.run")
    def test_compose_returns_output_path(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """compose() returns the out path on success."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )

        work_dir = tmp_path / "work"
        work_dir.mkdir()
        out_path = tmp_path / "output.mp4"

        scenes = [
            CompositionJob(
                scene_id=1, frames_dir=tmp_path / "s1", audio_path=tmp_path / "a1.mp3"
            ),
        ]

        composer = Composer(fps=15, resolution="720p")
        result = composer.compose(scenes, work_dir, out_path)

        assert result == out_path
