"""FFmpeg-based video composition.

Encodes each scene's frames + narration into an MP4 segment, joins the segments
(crossfaded, or a plain stream-copy concat when transitions are disabled), and
optionally mixes background music ducked under the narration.
"""

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
    """Encodes scene frame sequences + audio into MP4 segments and joins them.

    Args:
        fps: Frame rate for encoding (e.g. 24).
        resolution: Target resolution string (e.g. "720p"). Currently informational;
            the actual resolution is determined by the input frame dimensions.
        transition: Crossfade duration in seconds between scenes. 0 disables
            transitions and falls back to a plain concat (stream copy). Keep it
            no larger than the trailing silence each segment carries (the
            pipeline pads every scene with a tail pad), so the crossfade blends
            over silence rather than overlapping spoken narration.
    """

    def __init__(self, fps: int, resolution: str, transition: float = 0.5) -> None:
        self.fps = fps
        self.resolution = resolution
        self.transition = transition

    def compose(
        self,
        scenes: list[CompositionJob],
        work_dir: Path,
        out: Path,
        music: Path | None = None,
        durations: list[float] | None = None,
    ) -> Path:
        """Encode scenes to segments, join them, and optionally mix background music.

        Args:
            scenes: Ordered list of composition jobs (one per scene).
            work_dir: Working directory for intermediate files (segments, concat.txt).
            out: Final output MP4 path.
            music: Optional background music file to duck under narration at -18dB.
            durations: Per-scene segment durations in seconds, same order as
                ``scenes``. When supplied, they drive the crossfade offsets
                directly; otherwise each segment is measured with ffprobe. The
                caller (the pipeline) already knows these from the narration
                stage, so passing them avoids a probe subprocess per segment.

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

        # Step 2: Join the segments — crossfaded when transitions are enabled
        # and there is more than one scene; plain concat (stream copy) otherwise.
        concat_out = out if music is None else work_dir / "concat_output.mp4"
        if len(segment_paths) > 1 and self.transition > 0:
            if durations is not None and len(durations) == len(segment_paths):
                seg_durations = durations
            else:
                seg_durations = [self._probe_duration(seg) for seg in segment_paths]
            self._join_with_transitions(segment_paths, seg_durations, concat_out)
        else:
            concat_file = work_dir / "concat.txt"
            with open(concat_file, "w") as f:
                f.writelines(f"file '{seg}'\n" for seg in segment_paths)
            self._concat_segments(concat_file, concat_out)

        # Step 3: Optional background music, ducked under the narration.
        if music is not None:
            self._mix_music(concat_out, music, out)

        return out

    def _encode_segment(self, job: CompositionJob, seg_path: Path) -> None:
        """Encode a single scene's frames + audio to an MP4 segment.

        The frame track spans the full scene duration (narration + tail pad),
        but the narration MP3 is only as long as the speech. ``apad`` pads the
        audio with trailing silence so ``-shortest`` cuts on the (longer) frame
        track instead of dropping the tail pad — the segment keeps its silent
        tail, which is where scene crossfades land.
        """
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
            "-af",
            "apad",
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

    def _probe_duration(self, path: Path) -> float:
        """Return a media file's duration in seconds via ffprobe.

        Raises:
            CompositionError: If ffprobe fails or returns no duration.
        """
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            stderr = result.stderr[:1024] if result.stderr else "(no stderr)"
            raise CompositionError(
                message=(
                    f"ffprobe failed reading duration of {path.name} "
                    f"(exit code {result.returncode})"
                ),
                ffmpeg_stderr=stderr,
            )
        try:
            return float(result.stdout.strip())
        except ValueError as exc:
            raise CompositionError(
                message=f"ffprobe returned no duration for {path.name}",
                ffmpeg_stderr=(result.stdout or "").strip()[:1024],
            ) from exc

    def _join_with_transitions(
        self, segments: list[Path], durations: list[float], out_path: Path
    ) -> None:
        """Join segments with a crossfade on video (xfade) and audio (acrossfade).

        Unlike the concat-demuxer path this re-encodes the joined result, but it
        remains deterministic: the same inputs and FFmpeg build always produce
        the same output.

        The ``xfade`` filters are chained, so each transition's ``offset`` is
        measured on the running timeline of everything joined so far. Each join
        overlaps the two clips for ``fade`` seconds, shortening the timeline by
        that much, which the accumulator accounts for.

        Args:
            segments: Ordered segment MP4 paths.
            durations: Per-segment durations in seconds (same order).
            out_path: Joined output MP4 path.
        """
        # Clamp the fade to at most half of the shortest scene so every xfade
        # offset leaves room for the transition on both inputs.
        fade = min(self.transition, min(durations) / 2)
        # Emit timings at millisecond precision: finer than any frame, and free
        # of the trailing float-repr noise raw interpolation would leak into the
        # filter string.
        fade_str = f"{fade:.3f}"

        video_chain = ""
        audio_chain = ""
        timeline = durations[0]  # length of everything joined so far
        for i in range(1, len(segments)):
            offset = timeline - fade
            prev_v = "[0:v]" if i == 1 else f"[v{i - 1}]"
            prev_a = "[0:a]" if i == 1 else f"[a{i - 1}]"
            video_chain += (
                f"{prev_v}[{i}:v]xfade=transition=fade:"
                f"duration={fade_str}:offset={offset:.3f}[v{i}];"
            )
            audio_chain += f"{prev_a}[{i}:a]acrossfade=d={fade_str}[a{i}];"
            timeline += durations[i] - fade

        last = len(segments) - 1
        filter_complex = (video_chain + audio_chain).rstrip(";")

        cmd = ["ffmpeg", "-y"]
        for seg in segments:
            cmd += ["-i", str(seg)]
        cmd += [
            "-filter_complex",
            filter_complex,
            "-map",
            f"[v{last}]",
            "-map",
            f"[a{last}]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-map_metadata",
            "-1",
            str(out_path),
        ]

        self._run_ffmpeg(cmd, context="joining segments with transitions")

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
