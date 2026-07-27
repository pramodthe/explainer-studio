"""Core data schemas for Explainer Studio.

Defines SceneKind, Scene, and Script models with pydantic validation,
file I/O, and per-template JSON Schema validation.
"""

from __future__ import annotations

import json
import warnings
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, field_validator, model_validator

# Target audience for a script. Shared with providers.llm_base.ScriptRequest so
# both ends of the scripting stage accept exactly the same values.
Audience = Literal["kid", "student", "adult"]

# ---------------------------------------------------------------------------
# SceneKind enum
# ---------------------------------------------------------------------------


class SceneKind(str, Enum):
    """Supported scene template types."""

    TITLE = "title"
    CONCEPT = "concept"
    STEPS = "steps"
    COMPARE = "compare"
    CHART = "chart"
    TAKEAWAY = "takeaway"
    ANIMATION = "animation"


# ---------------------------------------------------------------------------
# Scene model
# ---------------------------------------------------------------------------

_NARRATION_SOFT_LIMIT = 400


class Scene(BaseModel):
    """A single scene in an explainer script."""

    id: int
    kind: SceneKind
    title: str
    narration: str = ""
    data: dict[str, Any] = {}
    duration_hint: float | None = None

    @field_validator("narration")
    @classmethod
    def _check_narration_length(cls, v: str) -> str:
        if len(v) > _NARRATION_SOFT_LIMIT:
            warnings.warn(
                f"Narration exceeds ~{_NARRATION_SOFT_LIMIT} character soft limit "
                f"(got {len(v)} chars). Consider shortening for pacing.",
                UserWarning,
                stacklevel=2,
            )
        return v


# ---------------------------------------------------------------------------
# Protocol for template registry (avoids circular imports)
# ---------------------------------------------------------------------------


@runtime_checkable
class TemplateMeta(Protocol):
    """Minimal interface for template metadata used in validation."""

    @property
    def schema(self) -> dict[str, Any]: ...


@runtime_checkable
class TemplateRegistry(Protocol):
    """Minimal interface for a registry that provides templates by kind."""

    def get_template(self, kind: SceneKind) -> TemplateMeta: ...


# ---------------------------------------------------------------------------
# Script model
# ---------------------------------------------------------------------------


class Script(BaseModel):
    """A complete explainer script containing multiple scenes."""

    topic: str
    language: str = "en"
    audience: Audience = "student"
    scenes: list[Scene]

    @model_validator(mode="after")
    def _validate_scenes(self) -> Script:
        scenes = self.scenes
        if len(scenes) < 3 or len(scenes) > 6:
            raise ValueError(f"Script must contain 3-6 scenes, got {len(scenes)}")
        if scenes[0].kind != SceneKind.TITLE:
            raise ValueError(
                f"First scene must be kind='title', got '{scenes[0].kind.value}'"
            )
        if scenes[-1].kind != SceneKind.TAKEAWAY:
            raise ValueError(
                f"Last scene must be kind='takeaway', got '{scenes[-1].kind.value}'"
            )
        return self

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    @classmethod
    def from_file(cls, path: str | Path) -> Script:
        """Load a Script from a JSON file.

        Args:
            path: Path to the JSON file containing the script data.

        Returns:
            A validated Script instance.

        Raises:
            FileNotFoundError: If the file does not exist.
            json.JSONDecodeError: If the file is not valid JSON.
            pydantic.ValidationError: If the data fails schema validation.
        """
        file_path = Path(path)
        data = json.loads(file_path.read_text(encoding="utf-8"))
        return cls.model_validate(data)

    def to_file(self, path: str | Path) -> None:
        """Serialize the script to a JSON file.

        Args:
            path: Destination file path. Parent directories are created
                  automatically if they don't exist.
        """
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            self.model_dump_json(indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Template-aware validation
    # ------------------------------------------------------------------

    def validate_with_templates(self, registry: TemplateRegistry) -> list[str]:
        """Validate each scene's data dict against the template's JSON Schema.

        Uses jsonschema for validation. Each scene's `data` is checked against
        the schema provided by the corresponding template in the registry.

        Args:
            registry: An object implementing `get_template(kind)` that returns
                      a TemplateMeta with a `schema` property (JSON Schema dict).

        Returns:
            A list of validation error strings (empty if all scenes pass).
        """
        try:
            import jsonschema
        except ImportError:
            # Graceful degradation: if jsonschema is not installed, skip
            # and issue a warning.
            warnings.warn(
                "jsonschema package not installed; skipping per-template "
                "data validation. Install with: pip install jsonschema",
                UserWarning,
                stacklevel=2,
            )
            return []

        errors: list[str] = []
        for scene in self.scenes:
            try:
                template = registry.get_template(scene.kind)
            except (KeyError, LookupError) as exc:
                errors.append(
                    f"Scene {scene.id} ({scene.kind.value}): template not found — {exc}"
                )
                continue

            schema = template.schema
            if not schema:
                # No schema defined for this template — nothing to validate.
                continue

            validator = jsonschema.Draft7Validator(schema)
            for error in validator.iter_errors(scene.data):
                path = ".".join(str(p) for p in error.absolute_path) or "(root)"
                errors.append(
                    f"Scene {scene.id} ({scene.kind.value}) data[{path}]: "
                    f"{error.message}"
                )
        return errors
