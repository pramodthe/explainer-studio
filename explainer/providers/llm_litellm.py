"""LiteLLM-based LLM provider for Explainer Studio.

Uses litellm.completion() to generate scripts via any supported model string
(e.g. openai/gpt-5.6, gemini/gemini-3.6-flash, moonshot/kimi-k3).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from explainer.core.errors import ScriptValidationError
from explainer.core.sanitize import validate_animation_code
from explainer.core.schema import SceneKind, Script
from explainer.providers.llm_base import ScriptRequest

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_SYSTEM_PROMPT_PATH = _PROMPTS_DIR / "script_system.md"

_TIMEOUT_SECONDS = 300


def _load_system_prompt() -> str:
    """Load the system prompt from prompts/script_system.md."""
    return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def _build_user_message(request: ScriptRequest) -> str:
    """Build the user message from the script request parameters."""
    templates_desc = ""
    if request.available_templates:
        items = []
        for t in request.available_templates:
            schema_str = json.dumps(t.data_schema, indent=2) if t.data_schema else "{}"
            items.append(f"- **{t.kind}** ({t.name}): data schema = {schema_str}")
        templates_desc = "\n".join(items)
    else:
        templates_desc = (
            "- title (Title Card): data schema = {}\n"
            "- concept (Concept / Definition): data schema = "
            '{"bullets": ["string"], "diagram": {"type": "string", "labels": ["string"]}}\n'
            "- steps (Step-by-Step): data schema = "
            '{"steps": ["string"]}\n'
            "- compare (Comparison): data schema = "
            '{"left": {"label": "string", "points": ["string"]}, '
            '"right": {"label": "string", "points": ["string"]}}\n'
            "- chart (Chart): data schema = "
            '{"chart_type": "string", "labels": ["string"], "values": [0]}\n'
            "- takeaway (Key Takeaway): data schema = "
            '{"bullets": ["string"]}'
        )

    return (
        f"Generate an educational explainer script for the following:\n\n"
        f"**Topic:** {request.topic}\n"
        f"**Language:** {request.language}\n"
        f"**Audience:** {request.audience}\n"
        f"**Target duration:** {request.target_duration} seconds\n\n"
        f"**Available templates:**\n{templates_desc}\n\n"
        f"Respond ONLY with the JSON object. No markdown fences, no commentary."
    )


def _extract_json(text: str) -> dict[str, Any]:
    """Extract JSON from LLM response, handling markdown fences."""
    text = text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        # Remove first line (```json or ```) and last line (```)
        lines = text.split("\n")
        # Find opening fence
        start = 1
        # Find closing fence
        end = len(lines) - 1
        while end > start and not lines[end].strip().startswith("```"):
            end -= 1
        text = "\n".join(lines[start:end])
    parsed: dict[str, Any] = json.loads(text)
    return parsed


class LiteLLMProvider:
    """LLM provider using litellm for script generation.

    Supports any model string that litellm accepts (e.g. openai/gpt-5.6,
    gemini/gemini-3.6-flash, anthropic/claude-sonnet-5).

    Args:
        model: The litellm model string. Defaults to "openai/gpt-5.6-luna".
    """

    def __init__(self, model: str = "openai/gpt-5.6-luna") -> None:
        self._model = model

    def generate_script(self, request: ScriptRequest) -> Script:
        """Generate a validated Script via litellm.completion().

        Calls the LLM with the system prompt and user message. Parses the
        JSON response, validates against the Script pydantic model. On
        validation failure, retries once with the error appended to the
        user message. Raises ScriptValidationError if the retry also fails.

        Args:
            request: The script generation parameters.

        Returns:
            A validated Script instance.

        Raises:
            ScriptValidationError: If validation fails after retry.
        """
        import litellm

        system_prompt = _load_system_prompt()
        user_message = _build_user_message(request)

        # First attempt
        try:
            script = self._attempt(litellm, system_prompt, user_message)
            return script
        except (ValidationError, json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning(
                "First LLM attempt failed validation: %s. Retrying with error context.",
                exc,
            )
            error_context = str(exc)
        except Exception as exc:  # noqa: BLE001
            # Transport/provider failure (auth, quota, network, server error).
            # Unlike a malformed response, resending the prompt cannot fix it,
            # so surface it as a typed stage error instead of retrying.
            raise ScriptValidationError(
                f"LLM request failed ({type(exc).__name__}): {exc}"
            ) from exc

        # Retry with error appended
        retry_message = (
            f"{user_message}\n\n"
            f"---\n"
            f"Your previous response failed validation with this error:\n"
            f"{error_context}\n\n"
            f"Please fix the issues and respond with valid JSON only."
        )

        try:
            script = self._attempt(litellm, system_prompt, retry_message)
            return script
        except (ValidationError, json.JSONDecodeError, KeyError, ValueError) as exc:
            raise ScriptValidationError(
                f"LLM output failed validation after retry: {exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise ScriptValidationError(
                f"LLM request failed ({type(exc).__name__}): {exc}"
            ) from exc

    def _supports_temperature(self, litellm: Any) -> bool:
        """Whether this model accepts a non-default temperature.

        Reasoning models (GPT-5 family, o-series, Claude/Gemini thinking models)
        reject any temperature but the default. litellm's `drop_params` only
        strips parameters it has metadata for, which newer models often lack, so
        the check is made explicitly here.
        """
        try:
            return not bool(litellm.supports_reasoning(self._model))
        except Exception:  # noqa: BLE001 - unknown model: assume it is accepted
            return True

    def _attempt(self, litellm: Any, system_prompt: str, user_message: str) -> Script:
        """Single LLM call attempt with parsing and validation."""
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "timeout": _TIMEOUT_SECONDS,
            # Let litellm strip any other parameters this model rejects.
            "drop_params": True,
        }
        if self._supports_temperature(litellm):
            kwargs["temperature"] = 0.7

        response = litellm.completion(**kwargs)

        content = response.choices[0].message.content
        if not content:
            raise ValueError("LLM returned empty response")

        data = _extract_json(content)
        script = Script.model_validate(data)

        # Animation scenes carry model-authored code. Raise ValueError so the
        # caller retries once with these messages appended (same path as
        # pydantic / JSON failures).
        violations: list[str] = []
        for scene in script.scenes:
            if scene.kind == SceneKind.ANIMATION:
                violations.extend(
                    f"scene {scene.id} ({scene.title}): {issue}"
                    for issue in validate_animation_code(scene.data)
                )
        if violations:
            raise ValueError(
                "Model-authored animation code is not reproducible:\n  "
                + "\n  ".join(violations)
            )

        return script


__all__ = ["LiteLLMProvider"]
