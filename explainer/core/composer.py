"""FFmpeg-based video composition: per-scene encoding + concat + optional music ducking."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from explainer.core.errors import CompositionError


@dataclass
class CompositionJob:
    """Describes one scene's assets for composition.

    Attributes:
        scene_id: Numeric identifier for ordering.
        frames_dir: Directory containing f0000.png, f0001.png, ... for this scene.
        audio_path: Path to the narration MP3 for this scene.
    """

    scene_id: int
    frames_dir: Path
    audio_path: Path


class Composer:
    """Encodes scene frame sequences + audio into MP4 segments and concatenates them.

    Args:
        fps: Frame rate for encoding (e.g. 15).
        resolution: Target resolution string (e.g. "720p"). Currently informational;
            the actual resolution is determined by the input frame dimensions.
    """

    def __init__(self, fps: int, resolution: str) -> None:
        self.fps = fps
        self.resolution = resolution

    def compose(
        self,
        scenes: list[CompositionJob],
        work_dir: Path,
        out: Path,
        music: Path | None = None,
    ) -> Path:
        """Encode scenes to segments, concatenate, and optionally mix background music.

        Args:
            scenes: Ordered list of composition jobs (one per scene).
            work_dir: Working directory for intermediate files (segments, concat.txt).
            out: Final output MP4 path.
            music: Optional background music file to duck under narration at -18dB.

        Returns:
            The output MP4 path.

        Raises:
            CompositionError: If any FFmpeg command fails.
        """
        segments_dir = work_dir / "segments"
        segments_dir.mkdir(parents=True, exist_ok=True)

        segment_paths: list[Path] = []

        # Step 1: Encode each scene's frames + audio into a segment MP4
        for job in scenes:
            seg_path = segments_dir / f"seg{job.scene_id}.mp4"
            self._encode_segment(job, seg_path)
            segment_paths.append(seg_path)

        # Step 2: Write concat.txt
        concat_file = work_dir / "concat.txt"
        with open(concat_file, "w") as f:
            f.writelines(f"file '{seg}'\n" for seg in segment_paths)

        # Step 3: Concatenate segments
        concat_out = out if music is None else work_dir / "concat_output.mp4"
        self._concat_segments(concat_file, concat_out)

        # Step 4: Optional music ducking
        if music is not None:
            self._mix_music(concat_out, music, out)

        return out

    def _encode_segment(self, job: CompositionJob, seg_path: Path) -> None:
        """Encode a single scene's frames + audio to an MP4 segment."""
        frames_pattern = str(job.frames_dir / "f%04d.png")

        cmd = [
            "ffmpeg",
            "-y",
            "-framerate",
            str(self.fps),
            "-i",
            frames_pattern,
            "-i",
            str(job.audio_path),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            "-map_metadata",
            "-1",
            str(seg_path),
        ]

        self._run_ffmpeg(cmd, context=f"encoding scene {job.scene_id}")

    def _concat_segments(self, concat_file: Path, out_path: Path) -> None:
        """Concatenate segment MP4s using FFmpeg concat demuxer."""
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            "-map_metadata",
            "-1",
            str(out_path),
        ]

        self._run_ffmpeg(cmd, context="concatenating segments")

    def _mix_music(self, video_path: Path, music_path: Path, out_path: Path) -> None:
        """Mix background music ducked to -18dB under narration using amix filter."""
        # amix with volume weighting: voice at full volume, music at -18dB
        # -18dB ≈ 0.125 linear amplitude
        filter_complex = (
            "[1:a]volume=0.125[bg];"
            "[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(music_path),
            "-filter_complex",
            filter_complex,
            "-map",
            "0:v",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-map_metadata",
            "-1",
            str(out_path),
        ]

        self._run_ffmpeg(cmd, context="mixing background music")

    def _run_ffmpeg(self, cmd: list[str], context: str) -> None:
        """Execute an FFmpeg command and raise CompositionError on failure.

        Args:
            cmd: The full FFmpeg command as a list of arguments.
            context: Description of what this command does (for error messages).

        Raises:
            CompositionError: If the process returns a non-zero exit code.
        """
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            stderr = result.stderr[:1024] if result.stderr else "(no stderr)"
            raise CompositionError(
                message=f"FFmpeg failed during {context} (exit code {result.returncode})",
                ffmpeg_stderr=stderr,
            )
