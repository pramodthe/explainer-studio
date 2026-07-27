"""Unit tests for LLM provider interface and adapters."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from explainer.core.errors import ScriptValidationError
from explainer.core.schema import SceneKind, Script
from explainer.providers.llm_base import LLMProvider, ScriptRequest, TemplateInfo
from explainer.providers.llm_heuristic import HeuristicProvider
from explainer.providers.llm_litellm import (
    LiteLLMProvider,
    _build_user_message,
    _extract_json,
)

# ---------------------------------------------------------------------------
# ScriptRequest model tests
# ---------------------------------------------------------------------------


class TestScriptRequest:
    """Tests for the ScriptRequest model."""

    def test_minimal_request(self) -> None:
        req = ScriptRequest(topic="Gravity")
        assert req.topic == "Gravity"
        assert req.language == "en"
        assert req.audience == "student"
        assert req.target_duration == 60
        assert req.available_templates == []

    def test_full_request(self) -> None:
        templates = [
            TemplateInfo(kind="title", name="Title Card", data_schema={}),
            TemplateInfo(
                kind="concept", name="Concept", data_schema={"type": "object"}
            ),
        ]
        req = ScriptRequest(
            topic="Photosynthesis",
            language="zh",
            audience="kid",
            target_duration=90,
            available_templates=templates,
        )
        assert req.topic == "Photosynthesis"
        assert req.language == "zh"
        assert req.audience == "kid"
        assert req.target_duration == 90
        assert len(req.available_templates) == 2


# ---------------------------------------------------------------------------
# LLMProvider protocol tests
# ---------------------------------------------------------------------------


class TestLLMProviderProtocol:
    """Tests that adapters satisfy the LLMProvider protocol."""

    def test_heuristic_implements_protocol(self) -> None:
        provider = HeuristicProvider()
        assert isinstance(provider, LLMProvider)

    def test_litellm_implements_protocol(self) -> None:
        provider = LiteLLMProvider(model="openai/gpt-5.6-luna")
        assert isinstance(provider, LLMProvider)


# ---------------------------------------------------------------------------
# HeuristicProvider tests
# ---------------------------------------------------------------------------


class TestHeuristicProvider:
    """Tests for the offline heuristic script generator."""

    def test_produces_valid_script(self) -> None:
        provider = HeuristicProvider()
        request = ScriptRequest(topic="Gravity")
        script = provider.generate_script(request)

        assert isinstance(script, Script)
        assert script.topic == "Gravity"
        assert script.language == "en"
        assert script.audience == "student"

    def test_produces_4_scenes(self) -> None:
        provider = HeuristicProvider()
        request = ScriptRequest(topic="Electricity")
        script = provider.generate_script(request)

        assert len(script.scenes) == 4

    def test_first_scene_is_title(self) -> None:
        provider = HeuristicProvider()
        request = ScriptRequest(topic="DNA")
        script = provider.generate_script(request)

        assert script.scenes[0].kind == SceneKind.TITLE

    def test_last_scene_is_takeaway(self) -> None:
        provider = HeuristicProvider()
        request = ScriptRequest(topic="DNA")
        script = provider.generate_script(request)

        assert script.scenes[-1].kind == SceneKind.TAKEAWAY

    def test_scene_kinds_order(self) -> None:
        provider = HeuristicProvider()
        request = ScriptRequest(topic="Evolution")
        script = provider.generate_script(request)

        kinds = [s.kind for s in script.scenes]
        assert kinds == [
            SceneKind.TITLE,
            SceneKind.CONCEPT,
            SceneKind.STEPS,
            SceneKind.TAKEAWAY,
        ]

    def test_topic_appears_in_narration(self) -> None:
        provider = HeuristicProvider()
        request = ScriptRequest(topic="Quantum Mechanics")
        script = provider.generate_script(request)

        for scene in script.scenes:
            assert "Quantum Mechanics" in scene.narration

    def test_narration_within_limit(self) -> None:
        provider = HeuristicProvider()
        request = ScriptRequest(topic="A very long topic name for testing limits")
        script = provider.generate_script(request)

        for scene in script.scenes:
            assert len(scene.narration) <= 400

    def test_respects_language(self) -> None:
        provider = HeuristicProvider()
        request = ScriptRequest(topic="Gravity", language="zh")
        script = provider.generate_script(request)

        assert script.language == "zh"

    def test_respects_audience(self) -> None:
        provider = HeuristicProvider()
        request = ScriptRequest(topic="Gravity", audience="kid")
        script = provider.generate_script(request)

        assert script.audience == "kid"
        assert "kid" in script.scenes[0].narration

    def test_sequential_scene_ids(self) -> None:
        provider = HeuristicProvider()
        request = ScriptRequest(topic="Waves")
        script = provider.generate_script(request)

        ids = [s.id for s in script.scenes]
        assert ids == [1, 2, 3, 4]

    def test_concept_scene_has_bullets(self) -> None:
        provider = HeuristicProvider()
        request = ScriptRequest(topic="Friction")
        script = provider.generate_script(request)

        concept_scene = script.scenes[1]
        assert concept_scene.kind == SceneKind.CONCEPT
        assert "bullets" in concept_scene.data
        assert len(concept_scene.data["bullets"]) >= 1

    def test_steps_scene_has_steps(self) -> None:
        provider = HeuristicProvider()
        request = ScriptRequest(topic="Mitosis")
        script = provider.generate_script(request)

        steps_scene = script.scenes[2]
        assert steps_scene.kind == SceneKind.STEPS
        assert "steps" in steps_scene.data
        assert len(steps_scene.data["steps"]) >= 1


# ---------------------------------------------------------------------------
# LiteLLMProvider tests (mocked)
# ---------------------------------------------------------------------------


def _make_valid_script_json() -> str:
    """Create a valid script JSON string for mocking LLM responses."""
    return json.dumps(
        {
            "topic": "Gravity",
            "language": "en",
            "audience": "student",
            "scenes": [
                {
                    "id": 1,
                    "kind": "title",
                    "title": "Gravity",
                    "narration": "Welcome to our exploration of gravity.",
                    "data": {},
                },
                {
                    "id": 2,
                    "kind": "concept",
                    "title": "What is Gravity?",
                    "narration": "Gravity is the force that pulls objects toward each other.",
                    "data": {"bullets": ["Universal force", "Proportional to mass"]},
                },
                {
                    "id": 3,
                    "kind": "steps",
                    "title": "How Gravity Works",
                    "narration": "Here is how gravity works in simple steps.",
                    "data": {"steps": ["Mass creates gravity", "Distance weakens it"]},
                },
                {
                    "id": 4,
                    "kind": "takeaway",
                    "title": "Key Takeaway",
                    "narration": "Gravity keeps planets in orbit and us on the ground.",
                    "data": {
                        "bullets": ["Gravity is everywhere", "It shapes the universe"]
                    },
                },
            ],
        }
    )


class TestLiteLLMProvider:
    """Tests for the LiteLLM adapter with mocked API calls."""

    def test_successful_generation(self) -> None:
        provider = LiteLLMProvider(model="openai/gpt-5.6-luna")
        request = ScriptRequest(topic="Gravity")

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = _make_valid_script_json()

        with patch("litellm.completion", return_value=mock_response) as mock_comp:
            script = provider.generate_script(request)

        assert isinstance(script, Script)
        assert script.topic == "Gravity"
        assert len(script.scenes) == 4
        mock_comp.assert_called_once()

    def test_handles_markdown_fenced_response(self) -> None:
        provider = LiteLLMProvider(model="openai/gpt-5.6-luna")
        request = ScriptRequest(topic="Gravity")

        fenced_json = f"```json\n{_make_valid_script_json()}\n```"
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = fenced_json

        with patch("litellm.completion", return_value=mock_response):
            script = provider.generate_script(request)

        assert isinstance(script, Script)
        assert script.topic == "Gravity"

    def test_retries_on_validation_failure(self) -> None:
        provider = LiteLLMProvider(model="openai/gpt-5.6-luna")
        request = ScriptRequest(topic="Gravity")

        # First response: invalid (missing required scenes structure)
        invalid_response = MagicMock()
        invalid_response.choices = [MagicMock()]
        invalid_response.choices[0].message.content = json.dumps({"topic": "Gravity"})

        # Second response: valid
        valid_response = MagicMock()
        valid_response.choices = [MagicMock()]
        valid_response.choices[0].message.content = _make_valid_script_json()

        with patch(
            "litellm.completion", side_effect=[invalid_response, valid_response]
        ) as mock_comp:
            script = provider.generate_script(request)

        assert isinstance(script, Script)
        assert mock_comp.call_count == 2

    def test_retries_on_animation_code_violation(self) -> None:
        """Forbidden draw(t) constructs get one corrective LLM retry."""
        provider = LiteLLMProvider(model="openai/gpt-5.6-luna")
        request = ScriptRequest(topic="Orbit")

        bad_script = {
            "topic": "Orbit",
            "language": "en",
            "audience": "student",
            "scenes": [
                {
                    "id": 1,
                    "kind": "title",
                    "title": "Orbit",
                    "narration": "Welcome.",
                    "data": {},
                },
                {
                    "id": 2,
                    "kind": "animation",
                    "title": "Path",
                    "narration": "Watch the path.",
                    "data": {
                        "markup": "<svg><circle id='c'/></svg>",
                        "js": "var x = Date.now();",
                    },
                },
                {
                    "id": 3,
                    "kind": "takeaway",
                    "title": "Done",
                    "narration": "That is an orbit.",
                    "data": {"bullets": ["Elliptical"]},
                },
            ],
        }
        good_script = json.loads(json.dumps(bad_script))
        good_script["scenes"][1]["data"]["js"] = (
            "document.getElementById('c').setAttribute('r', String(10 + 20 * t));"
        )

        bad_response = MagicMock()
        bad_response.choices = [MagicMock()]
        bad_response.choices[0].message.content = json.dumps(bad_script)

        good_response = MagicMock()
        good_response.choices = [MagicMock()]
        good_response.choices[0].message.content = json.dumps(good_script)

        with patch(
            "litellm.completion", side_effect=[bad_response, good_response]
        ) as mock_comp:
            script = provider.generate_script(request)

        assert isinstance(script, Script)
        assert mock_comp.call_count == 2
        retry_messages = mock_comp.call_args_list[1].kwargs["messages"]
        user_retry = retry_messages[1]["content"]
        assert "Date.now" in user_retry
        assert "animation" in user_retry.lower() or "reproducible" in user_retry.lower()

    def test_raises_after_retry_failure(self) -> None:
        provider = LiteLLMProvider(model="openai/gpt-5.6-luna")
        request = ScriptRequest(topic="Gravity")

        # Both responses invalid
        invalid_response = MagicMock()
        invalid_response.choices = [MagicMock()]
        invalid_response.choices[0].message.content = json.dumps({"topic": "Gravity"})

        with (
            patch("litellm.completion", return_value=invalid_response),
            pytest.raises(ScriptValidationError),
        ):
            provider.generate_script(request)

    def test_raises_on_empty_response(self) -> None:
        provider = LiteLLMProvider(model="openai/gpt-5.6-luna")
        request = ScriptRequest(topic="Gravity")

        empty_response = MagicMock()
        empty_response.choices = [MagicMock()]
        empty_response.choices[0].message.content = ""

        # Both attempts return empty
        with (
            patch("litellm.completion", return_value=empty_response),
            pytest.raises(ScriptValidationError),
        ):
            provider.generate_script(request)

    def test_api_error_becomes_typed_stage_error(self) -> None:
        """Provider/transport failures must not escape as raw tracebacks."""
        provider = LiteLLMProvider(model="gemini/gemini-3.6-flash")
        request = ScriptRequest(topic="Gravity")

        api_error = RuntimeError("429 RESOURCE_EXHAUSTED: credits depleted")

        with (
            patch("litellm.completion", side_effect=api_error) as mock_completion,
            pytest.raises(ScriptValidationError) as exc_info,
        ):
            provider.generate_script(request)

        # The provider message must survive for the user to act on it.
        assert "RESOURCE_EXHAUSTED" in str(exc_info.value)
        # Resending the prompt cannot fix an API error, so there is no retry.
        assert mock_completion.call_count == 1

    def test_validation_failure_still_retries_once(self) -> None:
        """A malformed response is worth one retry, unlike an API error."""
        provider = LiteLLMProvider(model="openai/gpt-5.6-luna")
        request = ScriptRequest(topic="Gravity")

        bad = MagicMock()
        bad.choices = [MagicMock()]
        bad.choices[0].message.content = json.dumps({"topic": "Gravity"})

        with (
            patch("litellm.completion", return_value=bad) as mock_completion,
            pytest.raises(ScriptValidationError),
        ):
            provider.generate_script(request)

        assert mock_completion.call_count == 2

    def test_passes_model_to_litellm(self) -> None:
        provider = LiteLLMProvider(model="anthropic/claude-sonnet-5")
        request = ScriptRequest(topic="Gravity")

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = _make_valid_script_json()

        with patch("litellm.completion", return_value=mock_response) as mock_comp:
            provider.generate_script(request)

        call_kwargs = mock_comp.call_args[1]
        assert call_kwargs["model"] == "anthropic/claude-sonnet-5"

    def test_sets_timeout(self) -> None:
        provider = LiteLLMProvider(model="openai/gpt-5.6-luna")
        request = ScriptRequest(topic="Gravity")

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = _make_valid_script_json()

        with patch("litellm.completion", return_value=mock_response) as mock_comp:
            provider.generate_script(request)

        call_kwargs = mock_comp.call_args[1]
        assert call_kwargs["timeout"] == 300


# ---------------------------------------------------------------------------
# Utility function tests
# ---------------------------------------------------------------------------


class TestExtractJson:
    """Tests for the JSON extraction helper."""

    def test_plain_json(self) -> None:
        raw = '{"topic": "test"}'
        assert _extract_json(raw) == {"topic": "test"}

    def test_fenced_json(self) -> None:
        raw = '```json\n{"topic": "test"}\n```'
        assert _extract_json(raw) == {"topic": "test"}

    def test_fenced_without_lang(self) -> None:
        raw = '```\n{"topic": "test"}\n```'
        assert _extract_json(raw) == {"topic": "test"}

    def test_whitespace_padding(self) -> None:
        raw = '  \n  {"topic": "test"}  \n  '
        assert _extract_json(raw) == {"topic": "test"}


class TestBuildUserMessage:
    """Tests for user message construction."""

    def test_includes_topic(self) -> None:
        request = ScriptRequest(topic="Gravity")
        msg = _build_user_message(request)
        assert "Gravity" in msg

    def test_includes_language(self) -> None:
        request = ScriptRequest(topic="Test", language="zh")
        msg = _build_user_message(request)
        assert "zh" in msg

    def test_includes_audience(self) -> None:
        request = ScriptRequest(topic="Test", audience="kid")
        msg = _build_user_message(request)
        assert "kid" in msg

    def test_includes_duration(self) -> None:
        request = ScriptRequest(topic="Test", target_duration=90)
        msg = _build_user_message(request)
        assert "90" in msg

    def test_includes_custom_templates(self) -> None:
        templates = [
            TemplateInfo(kind="title", name="My Title", data_schema={}),
        ]
        request = ScriptRequest(topic="Test", available_templates=templates)
        msg = _build_user_message(request)
        assert "title" in msg
        assert "My Title" in msg
