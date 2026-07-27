"""Unit tests for explainer.core.schema — SceneKind, Scene, Script."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest
from pydantic import ValidationError

from explainer.core.schema import Scene, SceneKind, Script

# ---------------------------------------------------------------------------
# SceneKind
# ---------------------------------------------------------------------------


class TestSceneKind:
    def test_all_values(self):
        assert set(SceneKind) == {
            SceneKind.TITLE,
            SceneKind.CONCEPT,
            SceneKind.STEPS,
            SceneKind.COMPARE,
            SceneKind.CHART,
            SceneKind.TAKEAWAY,
            SceneKind.ANIMATION,
        }

    def test_string_values(self):
        assert SceneKind.TITLE == "title"
        assert SceneKind.CONCEPT == "concept"
        assert SceneKind.STEPS == "steps"
        assert SceneKind.COMPARE == "compare"
        assert SceneKind.CHART == "chart"
        assert SceneKind.TAKEAWAY == "takeaway"

    def test_is_string(self):
        assert isinstance(SceneKind.TITLE, str)


# ---------------------------------------------------------------------------
# Scene
# ---------------------------------------------------------------------------


class TestScene:
    def test_minimal_scene(self):
        s = Scene(id=1, kind=SceneKind.TITLE, title="Hello")
        assert s.id == 1
        assert s.kind == SceneKind.TITLE
        assert s.title == "Hello"
        assert s.narration == ""
        assert s.data == {}
        assert s.duration_hint is None

    def test_full_scene(self):
        s = Scene(
            id=2,
            kind=SceneKind.CONCEPT,
            title="Big Idea",
            narration="Some narration text.",
            data={"bullets": ["a", "b"]},
            duration_hint=12.5,
        )
        assert s.narration == "Some narration text."
        assert s.data == {"bullets": ["a", "b"]}
        assert s.duration_hint == 12.5

    def test_narration_soft_limit_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            Scene(id=1, kind=SceneKind.TITLE, title="T", narration="x" * 401)
            assert len(w) == 1
            assert "400" in str(w[0].message)

    def test_narration_at_limit_no_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            Scene(id=1, kind=SceneKind.TITLE, title="T", narration="x" * 400)
            assert len(w) == 0

    def test_kind_from_string(self):
        s = Scene(id=1, kind="concept", title="T")
        assert s.kind == SceneKind.CONCEPT


# ---------------------------------------------------------------------------
# Script validation
# ---------------------------------------------------------------------------


def _make_script(scenes: list[Scene] | None = None, **kwargs) -> Script:
    """Helper to create scripts with defaults."""
    if scenes is None:
        scenes = [
            Scene(id=1, kind=SceneKind.TITLE, title="Intro", narration="Hi"),
            Scene(id=2, kind=SceneKind.CONCEPT, title="Core", narration="Body"),
            Scene(id=3, kind=SceneKind.TAKEAWAY, title="End", narration="Bye"),
        ]
    return Script(topic="Test", scenes=scenes, **kwargs)


class TestScriptValidation:
    def test_valid_3_scenes(self):
        s = _make_script()
        assert len(s.scenes) == 3

    def test_valid_6_scenes(self):
        scenes = [
            Scene(id=1, kind=SceneKind.TITLE, title="T", narration="N"),
            Scene(id=2, kind=SceneKind.CONCEPT, title="T", narration="N"),
            Scene(id=3, kind=SceneKind.STEPS, title="T", narration="N"),
            Scene(id=4, kind=SceneKind.COMPARE, title="T", narration="N"),
            Scene(id=5, kind=SceneKind.CHART, title="T", narration="N"),
            Scene(id=6, kind=SceneKind.TAKEAWAY, title="T", narration="N"),
        ]
        s = _make_script(scenes=scenes)
        assert len(s.scenes) == 6

    def test_reject_too_few_scenes(self):
        with pytest.raises(ValueError, match="3-6 scenes"):
            Script(
                topic="X",
                scenes=[
                    Scene(id=1, kind=SceneKind.TITLE, title="T", narration="N"),
                    Scene(id=2, kind=SceneKind.TAKEAWAY, title="T", narration="N"),
                ],
            )

    def test_reject_too_many_scenes(self):
        with pytest.raises(ValueError, match="3-6 scenes"):
            Script(
                topic="X",
                scenes=[
                    Scene(
                        id=i,
                        kind=(
                            SceneKind.TITLE
                            if i == 1
                            else SceneKind.TAKEAWAY
                            if i == 7
                            else SceneKind.CONCEPT
                        ),
                        title="T",
                        narration="N",
                    )
                    for i in range(1, 8)
                ],
            )

    def test_reject_first_scene_not_title(self):
        with pytest.raises(ValueError, match="(?i)first scene.*title"):
            Script(
                topic="X",
                scenes=[
                    Scene(id=1, kind=SceneKind.CONCEPT, title="T", narration="N"),
                    Scene(id=2, kind=SceneKind.STEPS, title="T", narration="N"),
                    Scene(id=3, kind=SceneKind.TAKEAWAY, title="T", narration="N"),
                ],
            )

    def test_reject_last_scene_not_takeaway(self):
        with pytest.raises(ValueError, match="(?i)last scene.*takeaway"):
            Script(
                topic="X",
                scenes=[
                    Scene(id=1, kind=SceneKind.TITLE, title="T", narration="N"),
                    Scene(id=2, kind=SceneKind.STEPS, title="T", narration="N"),
                    Scene(id=3, kind=SceneKind.CONCEPT, title="T", narration="N"),
                ],
            )

    def test_audience_literal(self):
        _make_script(audience="kid")
        _make_script(audience="student")
        _make_script(audience="adult")

    def test_reject_invalid_audience(self):
        with pytest.raises(ValidationError):
            _make_script(audience="expert")

    def test_default_language(self):
        s = _make_script()
        assert s.language == "en"

    def test_default_audience(self):
        s = _make_script()
        assert s.audience == "student"


# ---------------------------------------------------------------------------
# Script file I/O
# ---------------------------------------------------------------------------


class TestScriptFileIO:
    def test_round_trip(self, tmp_path: Path):
        script = _make_script()
        path = tmp_path / "script.json"
        script.to_file(path)

        loaded = Script.from_file(path)
        assert loaded.topic == script.topic
        assert loaded.language == script.language
        assert loaded.audience == script.audience
        assert len(loaded.scenes) == len(script.scenes)
        for orig, loaded_s in zip(script.scenes, loaded.scenes, strict=True):
            assert orig.id == loaded_s.id
            assert orig.kind == loaded_s.kind
            assert orig.title == loaded_s.title
            assert orig.narration == loaded_s.narration

    def test_to_file_creates_parents(self, tmp_path: Path):
        script = _make_script()
        path = tmp_path / "nested" / "dir" / "script.json"
        script.to_file(path)
        assert path.exists()

    def test_from_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            Script.from_file("/nonexistent/path.json")

    def test_from_file_invalid_json(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text("not json at all", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            Script.from_file(path)

    def test_output_is_valid_json(self, tmp_path: Path):
        script = _make_script()
        path = tmp_path / "out.json"
        script.to_file(path)
        data = json.loads(path.read_text())
        assert data["topic"] == "Test"
        assert len(data["scenes"]) == 3


# ---------------------------------------------------------------------------
# Script.validate_with_templates
# ---------------------------------------------------------------------------


class _MockTemplateMeta:
    def __init__(self, schema: dict):
        self._schema = schema

    @property
    def schema(self) -> dict:
        return self._schema


class _MockRegistry:
    def __init__(self, templates: dict):
        self._templates = templates

    def get_template(self, kind: SceneKind):
        if kind not in self._templates:
            raise KeyError(f"No template for {kind}")
        return self._templates[kind]


class TestValidateWithTemplates:
    def _registry(self):
        return _MockRegistry(
            {
                SceneKind.TITLE: _MockTemplateMeta({"type": "object"}),
                SceneKind.CONCEPT: _MockTemplateMeta(
                    {
                        "type": "object",
                        "properties": {
                            "bullets": {"type": "array", "items": {"type": "string"}}
                        },
                        "required": ["bullets"],
                    }
                ),
                SceneKind.TAKEAWAY: _MockTemplateMeta({"type": "object"}),
            }
        )

    def test_valid_data_no_errors(self):
        script = Script(
            topic="T",
            scenes=[
                Scene(id=1, kind=SceneKind.TITLE, title="T", narration="N"),
                Scene(
                    id=2,
                    kind=SceneKind.CONCEPT,
                    title="T",
                    narration="N",
                    data={"bullets": ["a"]},
                ),
                Scene(id=3, kind=SceneKind.TAKEAWAY, title="T", narration="N"),
            ],
        )
        errors = script.validate_with_templates(self._registry())
        assert errors == []

    def test_missing_required_field(self):
        script = Script(
            topic="T",
            scenes=[
                Scene(id=1, kind=SceneKind.TITLE, title="T", narration="N"),
                Scene(id=2, kind=SceneKind.CONCEPT, title="T", narration="N", data={}),
                Scene(id=3, kind=SceneKind.TAKEAWAY, title="T", narration="N"),
            ],
        )
        errors = script.validate_with_templates(self._registry())
        assert len(errors) == 1
        assert "bullets" in errors[0]

    def test_wrong_type(self):
        script = Script(
            topic="T",
            scenes=[
                Scene(id=1, kind=SceneKind.TITLE, title="T", narration="N"),
                Scene(
                    id=2,
                    kind=SceneKind.CONCEPT,
                    title="T",
                    narration="N",
                    data={"bullets": 42},
                ),
                Scene(id=3, kind=SceneKind.TAKEAWAY, title="T", narration="N"),
            ],
        )
        errors = script.validate_with_templates(self._registry())
        assert len(errors) == 1

    def test_template_not_found(self):
        script = Script(
            topic="T",
            scenes=[
                Scene(id=1, kind=SceneKind.TITLE, title="T", narration="N"),
                Scene(id=2, kind=SceneKind.STEPS, title="T", narration="N"),
                Scene(id=3, kind=SceneKind.TAKEAWAY, title="T", narration="N"),
            ],
        )
        registry = _MockRegistry(
            {
                SceneKind.TITLE: _MockTemplateMeta({}),
                SceneKind.TAKEAWAY: _MockTemplateMeta({}),
            }
        )
        errors = script.validate_with_templates(registry)
        assert len(errors) == 1
        assert "not found" in errors[0]

    def test_empty_schema_passes(self):
        """Templates with empty schema should pass any data."""
        script = Script(
            topic="T",
            scenes=[
                Scene(
                    id=1,
                    kind=SceneKind.TITLE,
                    title="T",
                    narration="N",
                    data={"anything": True},
                ),
                Scene(
                    id=2,
                    kind=SceneKind.CONCEPT,
                    title="T",
                    narration="N",
                    data={"bullets": ["x"]},
                ),
                Scene(id=3, kind=SceneKind.TAKEAWAY, title="T", narration="N"),
            ],
        )
        registry = _MockRegistry(
            {
                SceneKind.TITLE: _MockTemplateMeta({}),
                SceneKind.CONCEPT: _MockTemplateMeta(
                    {
                        "type": "object",
                        "properties": {"bullets": {"type": "array"}},
                        "required": ["bullets"],
                    }
                ),
                SceneKind.TAKEAWAY: _MockTemplateMeta({}),
            }
        )
        errors = script.validate_with_templates(registry)
        assert errors == []
