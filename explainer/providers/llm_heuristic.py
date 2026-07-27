"""Heuristic (offline) LLM provider for Explainer Studio.

Produces a fixed 4-scene structure without any API call. Useful as a
zero-config fallback when no LLM API key is configured.
"""

from __future__ import annotations

from explainer.core.schema import Scene, SceneKind, Script
from explainer.providers.llm_base import ScriptRequest


class HeuristicProvider:
    """Offline script generator producing a fixed 4-scene structure.

    Scenes: title → concept → steps → takeaway.
    The topic, language, and audience are inserted into placeholder narration text.
    No API call is made.
    """

    def generate_script(self, request: ScriptRequest) -> Script:
        """Generate a deterministic 4-scene script from the request.

        Args:
            request: The script generation parameters.

        Returns:
            A validated Script with 4 scenes (title, concept, steps, takeaway).
        """
        topic = request.topic
        audience = request.audience
        language = request.language

        scenes = [
            Scene(
                id=1,
                kind=SceneKind.TITLE,
                title=topic,
                narration=(
                    f"Welcome! Today we will explore {topic}. "
                    f"This explanation is designed for a {audience} audience."
                ),
                data={},
            ),
            Scene(
                id=2,
                kind=SceneKind.CONCEPT,
                title=f"What is {topic}?",
                narration=(
                    f"{topic} is a fundamental concept that helps us understand "
                    f"the world around us. Let's break it down into simple terms "
                    f"that are easy to follow."
                ),
                data={
                    "bullets": [
                        f"{topic} is a key concept",
                        "Understanding it opens many doors",
                        "Let's see how it works",
                    ],
                },
            ),
            Scene(
                id=3,
                kind=SceneKind.STEPS,
                title=f"How {topic} works",
                narration=(
                    f"Here are the main steps to understand {topic}. "
                    f"First, observe the basics. Then, connect the ideas together. "
                    f"Finally, apply what you've learned."
                ),
                data={
                    "steps": [
                        "Observe the basics",
                        "Connect the ideas together",
                        "Apply what you have learned",
                    ],
                },
            ),
            Scene(
                id=4,
                kind=SceneKind.TAKEAWAY,
                title="Key Takeaway",
                narration=(
                    f"To summarize, {topic} is an important concept. "
                    f"Remember the key steps, practice regularly, "
                    f"and you will master it in no time."
                ),
                data={
                    "bullets": [
                        f"{topic} is an important concept",
                        "Remember the key steps",
                        "Practice regularly to master it",
                    ],
                },
            ),
        ]

        return Script(
            topic=topic,
            language=language,
            audience=audience,
            scenes=scenes,
        )


__all__ = ["HeuristicProvider"]
