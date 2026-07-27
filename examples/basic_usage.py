"""Basic usage example for Explainer Studio.

Demonstrates how to use the Pipeline API to generate a video from a topic,
or render from a pre-built Script JSON file.
"""

from pathlib import Path

from explainer import Pipeline, Script
from explainer.core.pipeline import ProgressEvent


def on_progress(event: ProgressEvent) -> None:
    """Print progress events to stdout."""
    print(f"[{event.stage}] {event.pct:.0f}% — {event.message}")


def generate_from_topic():
    """Generate a video from a topic string using the full pipeline."""
    pipeline = Pipeline(
        llm=None,  # Uses heuristic (offline) script generator
        tts="edge",  # Free edge-tts, no API key needed
        on_progress=on_progress,
    )

    result = pipeline.generate(
        topic="photosynthesis",
        language="en",
        audience="student",
        target_duration=60,
        fps=15,
        resolution="720p",
        out="photosynthesis.mp4",
        keep_artifacts=False,
    )

    print(f"\nVideo saved to: {result.mp4_path}")
    print(f"Script had {len(result.script.scenes)} scenes")


def render_from_script():
    """Render a video from an existing Script JSON file.

    This skips LLM script generation and goes directly to
    narration → rendering → composition.
    """
    script_path = Path(__file__).parent / "photosynthesis_script.json"
    script = Script.from_file(script_path)

    print(f"Loaded script: {script.topic} ({len(script.scenes)} scenes)")

    pipeline = Pipeline(tts="edge", on_progress=on_progress)

    result = pipeline.render(
        script,
        out="photosynthesis_from_script.mp4",
        fps=15,
        resolution="720p",
    )

    print(f"\nVideo saved to: {result.mp4_path}")


if __name__ == "__main__":
    import sys

    if "--from-script" in sys.argv:
        render_from_script()
    else:
        generate_from_topic()
