"""LLM provider interface and request model for Explainer Studio."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from explainer.core.schema import Audience, Script


class TemplateInfo(BaseModel):
    """Lightweight template metadata passed to the LLM for script generation."""

    kind: str
    name: str
    data_schema: dict[str, Any] = Field(default_factory=dict, alias="schema")

    model_config = {"populate_by_name": True}


class ScriptRequest(BaseModel):
    """Request parameters for LLM script generation."""

    topic: str
    language: str = "en"
    audience: Audience = "student"
    target_duration: int = 60
    available_templates: list[TemplateInfo] = []


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol that all LLM adapters must implement."""

    def generate_script(self, request: ScriptRequest) -> Script:
        """Generate a validated Script from the given request.

        Args:
            request: The script generation parameters including topic,
                     language, audience, duration, and available templates.

        Returns:
            A validated Script instance.

        Raises:
            ScriptValidationError: If the LLM output fails validation
                                   after retry.
        """
        ...


__all__ = ["LLMProvider", "ScriptRequest", "TemplateInfo"]
