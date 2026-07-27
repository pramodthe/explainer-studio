"""Template registry: discovers and validates bundled, user, and third-party templates."""

from __future__ import annotations

import importlib.metadata
import json
import logging
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from explainer.core.schema import SceneKind

logger = logging.getLogger(__name__)

# Regex to detect external URLs in src= or href= attributes.
# Matches src="http://..." or href='https://...' (both quote styles).
_EXTERNAL_URL_PATTERN = re.compile(
    r"""(?:src|href)\s*=\s*["']https?://""",
    re.IGNORECASE,
)


class TemplateMeta(BaseModel):
    """Metadata for a discovered template."""

    model_config = ConfigDict(populate_by_name=True)

    kind: SceneKind
    name: str
    version: str
    data_schema: dict[str, Any] = {}
    default_style: dict[str, Any] = {}
    index_html: Path

    # Deliberately shadows pydantic's deprecated BaseModel.schema() so that
    # TemplateMeta satisfies the template Protocol used across the codebase.
    @property
    def schema(self) -> dict[str, Any]:  # type: ignore[override]
        """JSON Schema for template data validation (Protocol-compatible)."""
        return self.data_schema

    @field_validator("index_html")
    @classmethod
    def _index_html_must_exist(cls, v: Path) -> Path:
        if not v.is_file():
            raise ValueError(f"index.html does not exist: {v}")
        return v


class Registry:
    """Discovers templates from bundled dir, user dir, and entry points."""

    def __init__(self) -> None:
        self._templates: dict[SceneKind, TemplateMeta] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def discover(self) -> None:
        """Load templates from all sources in priority order.

        Sources (later wins on kind conflicts):
        1. Bundled templates in explainer/templates/*
        2. User directory ~/.explainer/templates/*
        3. Entry points registered under 'explainer.templates'
        """
        self._templates.clear()

        # 1. Bundled templates
        bundled_dir = Path(__file__).resolve().parent.parent / "templates"
        self._discover_from_directory(bundled_dir, source="bundled")

        # 2. User templates
        user_dir = Path.home() / ".explainer" / "templates"
        self._discover_from_directory(user_dir, source="user")

        # 3. Entry points
        self._discover_from_entry_points()

    def get_template(self, kind: SceneKind) -> TemplateMeta:
        """Return template metadata for the given scene kind.

        Raises:
            KeyError: If no template is registered for the kind.
        """
        try:
            return self._templates[kind]
        except KeyError:
            available = ", ".join(k.value for k in self._templates)
            raise KeyError(
                f"No template registered for kind '{kind.value}'. "
                f"Available: [{available}]"
            ) from None

    def list_templates(self) -> list[TemplateMeta]:
        """Return all discovered templates sorted by kind value."""
        return sorted(self._templates.values(), key=lambda t: t.kind.value)

    # ------------------------------------------------------------------
    # Internal discovery helpers
    # ------------------------------------------------------------------

    def _discover_from_directory(self, directory: Path, source: str) -> None:
        """Scan a directory for template subdirectories containing template.json."""
        if not directory.is_dir():
            logger.debug("Template directory does not exist, skipping: %s", directory)
            return

        for child in sorted(directory.iterdir()):
            if not child.is_dir():
                continue
            template_json = child / "template.json"
            if not template_json.is_file():
                logger.debug("No template.json in %s, skipping", child)
                continue
            self._load_template(template_json, source=source)

    def _discover_from_entry_points(self) -> None:
        """Load templates advertised via importlib.metadata entry points."""
        # The group= kwarg is available on all supported versions (>=3.10).
        eps = importlib.metadata.entry_points(group="explainer.templates")

        for ep in eps:
            try:
                obj = ep.load()
                # If the entry point is a callable (e.g. get_path function),
                # call it to obtain the actual path.
                if callable(obj) and not isinstance(obj, (Path, str)):
                    template_path = obj()
                else:
                    template_path = obj

                # Entry point should return a Path to the template directory
                if isinstance(template_path, Path):
                    template_json = template_path / "template.json"
                    if template_json.is_file():
                        self._load_template(
                            template_json, source=f"entry_point:{ep.name}"
                        )
                    else:
                        logger.warning(
                            "Entry point '%s' points to directory without template.json: %s",
                            ep.name,
                            template_path,
                        )
                elif isinstance(template_path, str):
                    # String path
                    tp = Path(template_path)
                    template_json = tp / "template.json"
                    if template_json.is_file():
                        self._load_template(
                            template_json, source=f"entry_point:{ep.name}"
                        )
                    else:
                        logger.warning(
                            "Entry point '%s' path has no template.json: %s",
                            ep.name,
                            tp,
                        )
                else:
                    logger.warning(
                        "Entry point '%s' returned unsupported type: %s",
                        ep.name,
                        type(template_path).__name__,
                    )
            # Third-party entry points are untrusted: a broken plugin must not
            # take down template discovery for everything else.
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to load entry point '%s': %s", ep.name, exc)

    def _load_template(self, template_json: Path, source: str) -> None:
        """Parse template.json, validate, and register the template."""
        template_dir = template_json.parent

        # Parse template.json
        try:
            raw = json.loads(template_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to parse %s (%s): %s", template_json, source, exc)
            return

        # Resolve index.html path
        index_html = template_dir / "index.html"
        if not index_html.is_file():
            logger.warning(
                "Template '%s' (%s) missing index.html at %s",
                raw.get("name", "unknown"),
                source,
                index_html,
            )
            return

        # Security check: reject external URLs in index.html
        if not self._validate_no_external_urls(index_html, source):
            return

        # Build TemplateMeta
        try:
            meta = TemplateMeta(
                kind=raw["kind"],
                name=raw.get("name", raw["kind"]),
                version=raw.get("version", "0.0.0"),
                data_schema=raw.get("schema", {}),
                default_style=raw.get("default_style", {}),
                index_html=index_html,
            )
        except (KeyError, ValueError) as exc:
            logger.warning(
                "Invalid template metadata in %s (%s): %s",
                template_json,
                source,
                exc,
            )
            return

        # Register (later sources override earlier)
        if meta.kind in self._templates:
            logger.debug(
                "Overriding template for '%s' (source: %s)", meta.kind.value, source
            )
        self._templates[meta.kind] = meta
        logger.debug(
            "Registered template '%s' v%s for kind '%s' (source: %s)",
            meta.name,
            meta.version,
            meta.kind.value,
            source,
        )

    def _validate_no_external_urls(self, index_html: Path, source: str) -> bool:
        """Return True if the template contains no external URLs in src/href.

        Rejects templates that reference http:// or https:// in src= or href=
        attributes. This prevents templates from loading external resources,
        which would break determinism and security sandboxing.
        """
        try:
            content = index_html.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Cannot read %s (%s): %s", index_html, source, exc)
            return False

        matches = _EXTERNAL_URL_PATTERN.findall(content)
        if matches:
            logger.warning(
                "Template at %s (%s) rejected: contains external URL references "
                "in src/href attributes. Templates must be self-contained.",
                index_html.parent,
                source,
            )
            return False
        return True
