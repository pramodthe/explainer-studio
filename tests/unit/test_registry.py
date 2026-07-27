"""Unit tests for explainer.core.registry."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from explainer.core.registry import _EXTERNAL_URL_PATTERN, Registry, TemplateMeta
from explainer.core.schema import SceneKind

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_template_dir(
    base: Path,
    kind: str = "concept",
    name: str = "Concept / Definition",
    version: str = "1.0.0",
    schema: dict | None = None,
    default_style: dict | None = None,
    index_html_content: str = "<html><body>Hello</body></html>",
    include_index: bool = True,
    include_template_json: bool = True,
) -> Path:
    """Helper to create a minimal template directory."""
    template_dir = base / kind
    template_dir.mkdir(parents=True, exist_ok=True)

    if include_template_json:
        meta = {
            "kind": kind,
            "name": name,
            "version": version,
            "schema": schema or {},
            "default_style": default_style or {"bg": "#0d1b2a", "accent": "#4fc3f7"},
        }
        (template_dir / "template.json").write_text(json.dumps(meta), encoding="utf-8")

    if include_index:
        (template_dir / "index.html").write_text(index_html_content, encoding="utf-8")

    return template_dir


@pytest.fixture
def bundled_dir(tmp_path: Path) -> Path:
    """Create a mock bundled templates directory."""
    d = tmp_path / "bundled"
    d.mkdir()
    return d


@pytest.fixture
def user_dir(tmp_path: Path) -> Path:
    """Create a mock user templates directory."""
    d = tmp_path / "user"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# TemplateMeta model tests
# ---------------------------------------------------------------------------


class TestTemplateMeta:
    def test_valid_template_meta(self, tmp_path: Path) -> None:
        index = tmp_path / "index.html"
        index.write_text("<html></html>", encoding="utf-8")

        meta = TemplateMeta(
            kind=SceneKind.CONCEPT,
            name="Concept / Definition",
            version="1.0.0",
            data_schema={"type": "object"},
            default_style={"bg": "#000"},
            index_html=index,
        )
        assert meta.kind == SceneKind.CONCEPT
        assert meta.name == "Concept / Definition"
        assert meta.version == "1.0.0"
        assert meta.schema == {"type": "object"}
        assert meta.index_html == index

    def test_missing_index_html_raises(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "nonexistent.html"
        with pytest.raises(ValueError, match="index.html does not exist"):
            TemplateMeta(
                kind=SceneKind.TITLE,
                name="Title",
                version="1.0.0",
                data_schema={},
                default_style={},
                index_html=nonexistent,
            )

    def test_invalid_kind_raises(self, tmp_path: Path) -> None:
        index = tmp_path / "index.html"
        index.write_text("<html></html>", encoding="utf-8")

        with pytest.raises(ValueError):
            TemplateMeta(
                kind="invalid_kind",  # type: ignore[arg-type]
                name="Bad",
                version="1.0.0",
                data_schema={},
                default_style={},
                index_html=index,
            )


# ---------------------------------------------------------------------------
# Registry discovery tests
# ---------------------------------------------------------------------------


class TestRegistryDiscover:
    def test_discover_from_bundled_directory(
        self, tmp_path: Path, bundled_dir: Path
    ) -> None:
        _make_template_dir(bundled_dir, kind="title", name="Title Card")
        _make_template_dir(bundled_dir, kind="concept", name="Concept Slide")

        registry = Registry()
        registry._discover_from_directory(bundled_dir, source="bundled")

        templates = registry.list_templates()
        assert len(templates) == 2
        kinds = {t.kind for t in templates}
        assert SceneKind.TITLE in kinds
        assert SceneKind.CONCEPT in kinds

    def test_discover_from_user_directory(self, tmp_path: Path, user_dir: Path) -> None:
        _make_template_dir(user_dir, kind="steps", name="Steps Template")

        registry = Registry()
        registry._discover_from_directory(user_dir, source="user")

        templates = registry.list_templates()
        assert len(templates) == 1
        assert templates[0].kind == SceneKind.STEPS
        assert templates[0].name == "Steps Template"

    def test_discover_nonexistent_directory_is_noop(self, tmp_path: Path) -> None:
        registry = Registry()
        registry._discover_from_directory(tmp_path / "does_not_exist", source="test")
        assert registry.list_templates() == []

    def test_discover_skips_non_directory_entries(self, bundled_dir: Path) -> None:
        # Create a file (not a directory) in templates dir
        (bundled_dir / "readme.txt").write_text("not a template", encoding="utf-8")

        registry = Registry()
        registry._discover_from_directory(bundled_dir, source="bundled")
        assert registry.list_templates() == []

    def test_discover_skips_dir_without_template_json(self, bundled_dir: Path) -> None:
        # Directory exists but has no template.json
        (bundled_dir / "empty_template").mkdir()
        (bundled_dir / "empty_template" / "index.html").write_text(
            "<html></html>", encoding="utf-8"
        )

        registry = Registry()
        registry._discover_from_directory(bundled_dir, source="bundled")
        assert registry.list_templates() == []

    def test_user_overrides_bundled(self, bundled_dir: Path, user_dir: Path) -> None:
        _make_template_dir(
            bundled_dir, kind="concept", name="Bundled Concept", version="1.0.0"
        )
        _make_template_dir(
            user_dir, kind="concept", name="User Concept", version="2.0.0"
        )

        registry = Registry()
        registry._discover_from_directory(bundled_dir, source="bundled")
        registry._discover_from_directory(user_dir, source="user")

        meta = registry.get_template(SceneKind.CONCEPT)
        assert meta.name == "User Concept"
        assert meta.version == "2.0.0"

    def test_full_discover_with_patched_paths(self, tmp_path: Path) -> None:
        bundled = tmp_path / "bundled_templates"
        bundled.mkdir()
        _make_template_dir(bundled, kind="title", name="Title")
        _make_template_dir(bundled, kind="takeaway", name="Takeaway")

        user = tmp_path / "user_templates"
        user.mkdir()
        _make_template_dir(user, kind="chart", name="Chart")

        registry = Registry()

        # Patch the directory paths used in discover()
        with (
            patch.object(
                Path,
                "home",
                return_value=tmp_path,
            ),
            patch(
                "explainer.core.registry.Path.home",
                return_value=tmp_path,
            ),
        ):
            # Directly use internal methods instead of patching complex paths
            registry._discover_from_directory(bundled, source="bundled")
            registry._discover_from_directory(user, source="user")

        templates = registry.list_templates()
        assert len(templates) == 3


# ---------------------------------------------------------------------------
# Registry get_template / list_templates tests
# ---------------------------------------------------------------------------


class TestRegistryGetTemplate:
    def test_get_template_existing_kind(self, bundled_dir: Path) -> None:
        _make_template_dir(bundled_dir, kind="title", name="Title")

        registry = Registry()
        registry._discover_from_directory(bundled_dir, source="bundled")

        meta = registry.get_template(SceneKind.TITLE)
        assert meta.kind == SceneKind.TITLE
        assert meta.name == "Title"

    def test_get_template_missing_raises_keyerror(self) -> None:
        registry = Registry()
        with pytest.raises(KeyError, match="No template registered"):
            registry.get_template(SceneKind.CHART)

    def test_list_templates_sorted_by_kind(self, bundled_dir: Path) -> None:
        # Create templates in non-alphabetical order
        _make_template_dir(bundled_dir, kind="title", name="Title")
        _make_template_dir(bundled_dir, kind="concept", name="Concept")
        _make_template_dir(bundled_dir, kind="chart", name="Chart")

        registry = Registry()
        registry._discover_from_directory(bundled_dir, source="bundled")

        templates = registry.list_templates()
        kinds = [t.kind.value for t in templates]
        assert kinds == sorted(kinds)

    def test_list_templates_empty_registry(self) -> None:
        registry = Registry()
        assert registry.list_templates() == []


# ---------------------------------------------------------------------------
# Template validation tests
# ---------------------------------------------------------------------------


class TestTemplateValidation:
    def test_rejects_template_missing_index_html(self, bundled_dir: Path) -> None:
        _make_template_dir(
            bundled_dir, kind="concept", name="No Index", include_index=False
        )

        registry = Registry()
        registry._discover_from_directory(bundled_dir, source="bundled")
        assert registry.list_templates() == []

    def test_rejects_template_with_external_src_url(self, bundled_dir: Path) -> None:
        _make_template_dir(
            bundled_dir,
            kind="concept",
            name="External Src",
            index_html_content='<html><img src="https://evil.com/pic.png"></html>',
        )

        registry = Registry()
        registry._discover_from_directory(bundled_dir, source="bundled")
        assert registry.list_templates() == []

    def test_rejects_template_with_external_href_url(self, bundled_dir: Path) -> None:
        _make_template_dir(
            bundled_dir,
            kind="steps",
            name="External Href",
            index_html_content='<html><link href="http://cdn.example.com/style.css"></html>',
        )

        registry = Registry()
        registry._discover_from_directory(bundled_dir, source="bundled")
        assert registry.list_templates() == []

    def test_accepts_template_with_local_src(self, bundled_dir: Path) -> None:
        _make_template_dir(
            bundled_dir,
            kind="concept",
            name="Local Src",
            index_html_content='<html><img src="./image.png"><script src="app.js"></script></html>',
        )

        registry = Registry()
        registry._discover_from_directory(bundled_dir, source="bundled")
        assert len(registry.list_templates()) == 1

    def test_accepts_template_with_data_uri(self, bundled_dir: Path) -> None:
        _make_template_dir(
            bundled_dir,
            kind="title",
            name="Data URI",
            index_html_content='<html><img src="data:image/png;base64,abc123"></html>',
        )

        registry = Registry()
        registry._discover_from_directory(bundled_dir, source="bundled")
        assert len(registry.list_templates()) == 1

    def test_rejects_invalid_json_template(self, bundled_dir: Path) -> None:
        template_dir = bundled_dir / "bad_json"
        template_dir.mkdir()
        (template_dir / "template.json").write_text(
            "not valid json{{{", encoding="utf-8"
        )
        (template_dir / "index.html").write_text("<html></html>", encoding="utf-8")

        registry = Registry()
        registry._discover_from_directory(bundled_dir, source="bundled")
        assert registry.list_templates() == []

    def test_rejects_template_json_missing_kind(self, bundled_dir: Path) -> None:
        template_dir = bundled_dir / "no_kind"
        template_dir.mkdir()
        meta = {"name": "No Kind", "version": "1.0.0"}
        (template_dir / "template.json").write_text(json.dumps(meta), encoding="utf-8")
        (template_dir / "index.html").write_text("<html></html>", encoding="utf-8")

        registry = Registry()
        registry._discover_from_directory(bundled_dir, source="bundled")
        assert registry.list_templates() == []


# ---------------------------------------------------------------------------
# External URL regex tests
# ---------------------------------------------------------------------------


class TestExternalUrlPattern:
    @pytest.mark.parametrize(
        "content",
        [
            'src="https://example.com/script.js"',
            "src='http://cdn.example.com/lib.js'",
            'href="https://fonts.googleapis.com/css"',
            "href='http://example.com/style.css'",
            'SRC="HTTPS://EXAMPLE.COM/img.png"',  # case insensitive
        ],
    )
    def test_detects_external_urls(self, content: str) -> None:
        assert _EXTERNAL_URL_PATTERN.search(content) is not None

    @pytest.mark.parametrize(
        "content",
        [
            'src="./local.js"',
            'src="data:image/png;base64,abc"',
            'href="#section"',
            'href="relative/path.html"',
            "no attributes at all",
            'src="file:///tmp/something"',
        ],
    )
    def test_allows_non_external_urls(self, content: str) -> None:
        assert _EXTERNAL_URL_PATTERN.search(content) is None


# ---------------------------------------------------------------------------
# Entry points discovery tests
# ---------------------------------------------------------------------------


class TestEntryPointsDiscovery:
    def test_discover_from_entry_points_with_path(self, tmp_path: Path) -> None:
        """Entry point that returns a Path to a template directory."""
        _make_template_dir(tmp_path, kind="compare", name="Compare via EP")

        class MockEntryPoint:
            name = "compare"

            def load(self):
                return tmp_path / "compare"

        with patch(
            "importlib.metadata.entry_points",
            return_value=[MockEntryPoint()],
        ):
            registry = Registry()
            registry._discover_from_entry_points()

        templates = registry.list_templates()
        assert len(templates) == 1
        assert templates[0].kind == SceneKind.COMPARE
        assert templates[0].name == "Compare via EP"

    def test_discover_from_entry_points_with_string(self, tmp_path: Path) -> None:
        """Entry point that returns a string path."""
        _make_template_dir(tmp_path, kind="chart", name="Chart via EP")

        class MockEntryPoint:
            name = "chart"

            def load(self):
                return str(tmp_path / "chart")

        with patch(
            "importlib.metadata.entry_points",
            return_value=[MockEntryPoint()],
        ):
            registry = Registry()
            registry._discover_from_entry_points()

        templates = registry.list_templates()
        assert len(templates) == 1
        assert templates[0].kind == SceneKind.CHART

    def test_discover_from_entry_points_handles_errors(self, tmp_path: Path) -> None:
        """Entry point that raises an exception is skipped gracefully."""

        class BadEntryPoint:
            name = "broken"

            def load(self):
                raise ImportError("Module not found")

        with patch(
            "importlib.metadata.entry_points",
            return_value=[BadEntryPoint()],
        ):
            registry = Registry()
            registry._discover_from_entry_points()

        assert registry.list_templates() == []

    def test_discover_from_entry_points_no_template_json(self, tmp_path: Path) -> None:
        """Entry point pointing to dir without template.json is skipped."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        class MockEntryPoint:
            name = "empty"

            def load(self):
                return empty_dir

        with patch(
            "importlib.metadata.entry_points",
            return_value=[MockEntryPoint()],
        ):
            registry = Registry()
            registry._discover_from_entry_points()

        assert registry.list_templates() == []
