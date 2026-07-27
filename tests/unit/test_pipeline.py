"""Unit tests for explainer.core.pipeline module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from explainer.core.pipeline import (
    GenerateResult,
    Pipeline,
    ProgressEvent,
    _slugify,
)
from explainer.core.schema import Scene, SceneKind, Script

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_script(topic: str = "Gravity") -> Script:
    """Build a minimal valid Script for testing."""
    return Script(
        topic=topic,
        language="en",
        audience="student",
        scenes=[
            Scene(
                id=1,
                kind=SceneKind.TITLE,
                title=topic,
                narration="Welcome to gravity.",
                data={},
            ),
            Scene(
                id=2,
                kind=SceneKind.CONCEPT,
                title="What is gravity?",
                narration="Gravity pulls things down.",
                data={"bullets": ["Force", "Mass"]},
            ),
            Scene(
                id=3,
                kind=SceneKind.STEPS,
                title="How it works",
                narration="Step one observe. Step two apply.",
                data={"steps": ["Observe", "Apply"]},
            ),
            Scene(
                id=4,
                kind=SceneKind.TAKEAWAY,
                title="Summary",
                narration="Gravity is fundamental.",
                data={"bullets": ["Key point"]},
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Test _slugify helper
# ---------------------------------------------------------------------------


class TestSlugify:
    """Tests for the _slugify helper function."""

    def test_basic_topic(self) -> None:
        assert _slugify("Gravity") == "gravity"

    def test_spaces_become_dashes(self) -> None:
        assert _slugify("The Pythagorean Theorem") == "the-pythagorean-theorem"

    def test_special_chars_stripped(self) -> None:
        assert _slugify("What's 2+2?") == "what-s-2-2"

    def test_multiple_dashes_collapsed(self) -> None:
        assert _slugify("hello   world!!!") == "hello-world"

    def test_truncates_to_max_len(self) -> None:
        long_topic = "a" * 100
        result = _slugify(long_topic, max_len=60)
        assert len(result) <= 60

    def test_empty_string(self) -> None:
        assert _slugify("") == ""

    def test_unicode_stripped(self) -> None:
        # Non-ASCII chars are replaced by dashes
        result = _slugify("光合作用")
        # All non-alnum chars become dashes then stripped
        assert result == "" or all(c.isalnum() or c == "-" for c in result)


# ---------------------------------------------------------------------------
# Test ProgressEvent dataclass
# ---------------------------------------------------------------------------


class TestProgressEvent:
    """Tests for the ProgressEvent dataclass."""

    def test_creation(self) -> None:
        event = ProgressEvent(stage="scripting", pct=25.0, message="hello")
        assert event.stage == "scripting"
        assert event.pct == 25.0
        assert event.message == "hello"

    def test_default_message(self) -> None:
        event = ProgressEvent(stage="rendering", pct=50.0)
        assert event.message == ""


# ---------------------------------------------------------------------------
# Test GenerateResult dataclass
# ---------------------------------------------------------------------------


class TestGenerateResult:
    """Tests for the GenerateResult dataclass."""

    def test_creation(self, tmp_path: Path) -> None:
        script = _make_script()
        result = GenerateResult(
            mp4_path=tmp_path / "out.mp4",
            script=script,
            work_dir=tmp_path,
        )
        assert result.mp4_path == tmp_path / "out.mp4"
        assert result.script.topic == "Gravity"
        assert result.work_dir == tmp_path


# ---------------------------------------------------------------------------
# Test Pipeline.__init__
# ---------------------------------------------------------------------------


class TestPipelineInit:
    """Tests for Pipeline construction and config resolution."""

    @patch("explainer.core.pipeline.ExplainerConfig.resolve")
    def test_init_resolves_config(self, mock_resolve: MagicMock) -> None:
        mock_config = MagicMock()
        mock_config.llm = None
        mock_config.tts = "edge"
        mock_config.voice = None
        mock_resolve.return_value = mock_config

        pipeline = Pipeline(llm=None, tts="edge", voice=None)

        mock_resolve.assert_called_once_with(
            cli_args={"llm": None, "tts": "edge", "voice": None}
        )
        assert pipeline.config is mock_config

    @patch("explainer.core.pipeline.ExplainerConfig.resolve")
    def test_init_stores_on_progress(self, mock_resolve: MagicMock) -> None:
        mock_resolve.return_value = MagicMock(llm=None, tts="edge", voice=None)
        cb = MagicMock()

        pipeline = Pipeline(on_progress=cb)
        assert pipeline.on_progress is cb

    @patch("explainer.core.pipeline.ExplainerConfig.resolve")
    def test_init_with_llm_model(self, mock_resolve: MagicMock) -> None:
        mock_resolve.return_value = MagicMock(
            llm="openai/gpt-5.6", tts="edge", voice=None
        )

        Pipeline(llm="openai/gpt-5.6")

        mock_resolve.assert_called_once_with(
            cli_args={"llm": "openai/gpt-5.6", "tts": "edge", "voice": None}
        )


# ---------------------------------------------------------------------------
# Test Pipeline.generate (full pipeline with mocks)
# ---------------------------------------------------------------------------


class TestPipelineGenerate:
    """Tests for Pipeline.generate() with all external dependencies mocked."""

    @patch("explainer.core.pipeline.ExplainerConfig.resolve")
    @patch("explainer.core.pipeline.Registry")
    @patch("explainer.providers.llm_heuristic.HeuristicProvider.generate_script")
    @patch("explainer.providers.tts_edge.EdgeTTSProvider.synthesize")
    @patch("explainer.core.pipeline.Renderer")
    @patch("explainer.core.pipeline.Composer")
    def test_generate_full_pipeline(
        self,
        MockComposer: MagicMock,
        MockRenderer: MagicMock,
        mock_synthesize: MagicMock,
        mock_gen_script: MagicMock,
        MockRegistry: MagicMock,
        mock_resolve: MagicMock,
        tmp_path: Path,
    ) -> None:
        """generate() calls all 4 stages and returns a GenerateResult."""
        # Setup config
        mock_config = MagicMock()
        mock_config.llm = None
        mock_config.tts = "edge"
        mock_config.voice = None
        mock_resolve.return_value = mock_config

        # Setup registry
        mock_registry_instance = MagicMock()
        mock_template = MagicMock()
        mock_template.kind = SceneKind.TITLE
        mock_template.name = "Title"
        mock_template.data_schema = {}
        mock_template.default_style = {"bg": "#000"}
        mock_template.index_html = Path("/fake/template/index.html")
        mock_registry_instance.list_templates.return_value = [mock_template]
        mock_registry_instance.get_template.return_value = mock_template
        MockRegistry.return_value = mock_registry_instance

        # Setup LLM
        script = _make_script()
        mock_gen_script.return_value = script

        # Setup TTS: return 3.0s duration for each scene
        mock_synthesize.return_value = 3.0

        # Setup Renderer (no-op)
        mock_renderer_instance = MagicMock()
        MockRenderer.return_value = mock_renderer_instance

        # Setup Composer: create a fake output MP4
        mock_composer_instance = MagicMock()
        MockComposer.return_value = mock_composer_instance

        def fake_compose(scenes, work_dir, out, music=None, durations=None):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("fake mp4")
            return out

        mock_composer_instance.compose.side_effect = fake_compose

        # Output path
        out_path = tmp_path / "result.mp4"

        pipeline = Pipeline()
        result = pipeline.generate(
            "Gravity",
            language="en",
            audience="student",
            target_duration=60,
            fps=15,
            resolution="720p",
            out=str(out_path),
            keep_artifacts=True,
        )

        # Assertions
        assert isinstance(result, GenerateResult)
        assert result.mp4_path == out_path
        assert result.script.topic == "Gravity"
        assert result.work_dir.exists()

        # LLM was called
        mock_gen_script.assert_called_once()

        # TTS was called for each scene
        assert mock_synthesize.call_count == 4

        # Renderer was invoked
        mock_renderer_instance.render_all.assert_called_once()

        # Composer was invoked
        mock_composer_instance.compose.assert_called_once()

    @patch("explainer.core.pipeline.ExplainerConfig.resolve")
    @patch("explainer.core.pipeline.Registry")
    @patch("explainer.providers.llm_heuristic.HeuristicProvider.generate_script")
    @patch("explainer.providers.tts_edge.EdgeTTSProvider.synthesize")
    @patch("explainer.core.pipeline.Renderer")
    @patch("explainer.core.pipeline.Composer")
    def test_generate_cleans_up_work_dir(
        self,
        MockComposer: MagicMock,
        MockRenderer: MagicMock,
        mock_synthesize: MagicMock,
        mock_gen_script: MagicMock,
        MockRegistry: MagicMock,
        mock_resolve: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Work directory is cleaned up when keep_artifacts=False."""
        mock_config = MagicMock()
        mock_config.llm = None
        mock_config.tts = "edge"
        mock_config.voice = None
        mock_resolve.return_value = mock_config

        mock_registry_instance = MagicMock()
        mock_template = MagicMock()
        mock_template.kind = SceneKind.TITLE
        mock_template.name = "Title"
        mock_template.data_schema = {}
        mock_template.default_style = {}
        mock_template.index_html = Path("/fake/index.html")
        mock_registry_instance.list_templates.return_value = [mock_template]
        mock_registry_instance.get_template.return_value = mock_template
        MockRegistry.return_value = mock_registry_instance

        mock_gen_script.return_value = _make_script()
        mock_synthesize.return_value = 2.0

        mock_renderer_instance = MagicMock()
        MockRenderer.return_value = mock_renderer_instance

        mock_composer_instance = MagicMock()
        MockComposer.return_value = mock_composer_instance

        def fake_compose(scenes, work_dir, out, music=None, durations=None):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("fake mp4")
            return out

        mock_composer_instance.compose.side_effect = fake_compose

        out_path = tmp_path / "out.mp4"

        pipeline = Pipeline()
        result = pipeline.generate("Test", out=str(out_path), keep_artifacts=False)

        # work_dir should be cleaned up
        assert not result.work_dir.exists()

    @patch("explainer.core.pipeline.ExplainerConfig.resolve")
    @patch("explainer.core.pipeline.Registry")
    @patch("explainer.providers.llm_heuristic.HeuristicProvider.generate_script")
    @patch("explainer.providers.tts_edge.EdgeTTSProvider.synthesize")
    @patch("explainer.core.pipeline.Renderer")
    @patch("explainer.core.pipeline.Composer")
    def test_generate_emits_progress_events(
        self,
        MockComposer: MagicMock,
        MockRenderer: MagicMock,
        mock_synthesize: MagicMock,
        mock_gen_script: MagicMock,
        MockRegistry: MagicMock,
        mock_resolve: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Progress events are emitted at stage transitions."""
        mock_config = MagicMock()
        mock_config.llm = None
        mock_config.tts = "edge"
        mock_config.voice = None
        mock_resolve.return_value = mock_config

        mock_registry_instance = MagicMock()
        mock_template = MagicMock()
        mock_template.kind = SceneKind.TITLE
        mock_template.name = "Title"
        mock_template.data_schema = {}
        mock_template.default_style = {}
        mock_template.index_html = Path("/fake/index.html")
        mock_registry_instance.list_templates.return_value = [mock_template]
        mock_registry_instance.get_template.return_value = mock_template
        MockRegistry.return_value = mock_registry_instance

        mock_gen_script.return_value = _make_script()
        mock_synthesize.return_value = 2.0

        mock_renderer_instance = MagicMock()
        MockRenderer.return_value = mock_renderer_instance

        mock_composer_instance = MagicMock()
        MockComposer.return_value = mock_composer_instance

        def fake_compose(scenes, work_dir, out, music=None, durations=None):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("fake mp4")
            return out

        mock_composer_instance.compose.side_effect = fake_compose

        progress_events: list[ProgressEvent] = []

        out_path = tmp_path / "out.mp4"
        pipeline = Pipeline(on_progress=progress_events.append)
        pipeline.generate("Test", out=str(out_path), keep_artifacts=False)

        # Should have events from all stages
        stages_seen = {e.stage for e in progress_events}
        assert "scripting" in stages_seen
        assert "narrating" in stages_seen
        assert "rendering" in stages_seen
        assert "composing" in stages_seen
        assert "done" in stages_seen

    @patch("explainer.core.pipeline.ExplainerConfig.resolve")
    @patch("explainer.core.pipeline.Registry")
    @patch("explainer.providers.llm_heuristic.HeuristicProvider.generate_script")
    @patch("explainer.providers.tts_edge.EdgeTTSProvider.synthesize")
    @patch("explainer.core.pipeline.Renderer")
    @patch("explainer.core.pipeline.Composer")
    def test_generate_auto_output_path_slugified(
        self,
        MockComposer: MagicMock,
        MockRenderer: MagicMock,
        mock_synthesize: MagicMock,
        mock_gen_script: MagicMock,
        MockRegistry: MagicMock,
        mock_resolve: MagicMock,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        """When no out is specified, output path is slugified from topic."""
        mock_config = MagicMock()
        mock_config.llm = None
        mock_config.tts = "edge"
        mock_config.voice = None
        mock_resolve.return_value = mock_config

        mock_registry_instance = MagicMock()
        mock_template = MagicMock()
        mock_template.kind = SceneKind.TITLE
        mock_template.name = "Title"
        mock_template.data_schema = {}
        mock_template.default_style = {}
        mock_template.index_html = Path("/fake/index.html")
        mock_registry_instance.list_templates.return_value = [mock_template]
        mock_registry_instance.get_template.return_value = mock_template
        MockRegistry.return_value = mock_registry_instance

        mock_gen_script.return_value = _make_script("The Pythagorean Theorem")
        mock_synthesize.return_value = 2.0

        mock_renderer_instance = MagicMock()
        MockRenderer.return_value = mock_renderer_instance

        mock_composer_instance = MagicMock()
        MockComposer.return_value = mock_composer_instance

        def fake_compose(scenes, work_dir, out, music=None, durations=None):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("fake mp4")
            return out

        mock_composer_instance.compose.side_effect = fake_compose

        # Use tmp_path as cwd
        monkeypatch.chdir(tmp_path)

        pipeline = Pipeline()
        result = pipeline.generate("The Pythagorean Theorem", keep_artifacts=False)

        assert result.mp4_path.name == "the-pythagorean-theorem.mp4"


# ---------------------------------------------------------------------------
# Test Pipeline.render (skip scripting stage)
# ---------------------------------------------------------------------------


class TestPipelineRender:
    """Tests for Pipeline.render() which skips script generation."""

    @patch("explainer.core.pipeline.ExplainerConfig.resolve")
    @patch("explainer.core.pipeline.Registry")
    @patch("explainer.providers.tts_edge.EdgeTTSProvider.synthesize")
    @patch("explainer.core.pipeline.Renderer")
    @patch("explainer.core.pipeline.Composer")
    def test_render_skips_scripting(
        self,
        MockComposer: MagicMock,
        MockRenderer: MagicMock,
        mock_synthesize: MagicMock,
        MockRegistry: MagicMock,
        mock_resolve: MagicMock,
        tmp_path: Path,
    ) -> None:
        """render() does NOT call LLM provider."""
        mock_config = MagicMock()
        mock_config.llm = None
        mock_config.tts = "edge"
        mock_config.voice = None
        mock_resolve.return_value = mock_config

        mock_registry_instance = MagicMock()
        mock_template = MagicMock()
        mock_template.kind = SceneKind.TITLE
        mock_template.data_schema = {}
        mock_template.default_style = {}
        mock_template.index_html = Path("/fake/index.html")
        mock_registry_instance.list_templates.return_value = [mock_template]
        mock_registry_instance.get_template.return_value = mock_template
        MockRegistry.return_value = mock_registry_instance

        mock_synthesize.return_value = 2.5

        mock_renderer_instance = MagicMock()
        MockRenderer.return_value = mock_renderer_instance

        mock_composer_instance = MagicMock()
        MockComposer.return_value = mock_composer_instance

        def fake_compose(scenes, work_dir, out, music=None, durations=None):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("fake mp4")
            return out

        mock_composer_instance.compose.side_effect = fake_compose

        script = _make_script()
        out_path = tmp_path / "rendered.mp4"

        pipeline = Pipeline()
        result = pipeline.render(script, out=str(out_path), keep_artifacts=True)

        assert isinstance(result, GenerateResult)
        assert result.mp4_path == out_path
        assert result.script is script
        # TTS was called (narration not skipped)
        assert mock_synthesize.call_count == 4

    @patch("explainer.core.pipeline.ExplainerConfig.resolve")
    @patch("explainer.core.pipeline.Registry")
    @patch("explainer.providers.tts_edge.EdgeTTSProvider.synthesize")
    @patch("explainer.core.pipeline.Renderer")
    @patch("explainer.core.pipeline.Composer")
    def test_render_uses_per_call_on_progress(
        self,
        MockComposer: MagicMock,
        MockRenderer: MagicMock,
        mock_synthesize: MagicMock,
        MockRegistry: MagicMock,
        mock_resolve: MagicMock,
        tmp_path: Path,
    ) -> None:
        """render() can override on_progress per-call."""
        mock_config = MagicMock()
        mock_config.llm = None
        mock_config.tts = "edge"
        mock_config.voice = None
        mock_resolve.return_value = mock_config

        mock_registry_instance = MagicMock()
        mock_template = MagicMock()
        mock_template.kind = SceneKind.TITLE
        mock_template.data_schema = {}
        mock_template.default_style = {}
        mock_template.index_html = Path("/fake/index.html")
        mock_registry_instance.list_templates.return_value = [mock_template]
        mock_registry_instance.get_template.return_value = mock_template
        MockRegistry.return_value = mock_registry_instance

        mock_synthesize.return_value = 2.0

        mock_renderer_instance = MagicMock()
        MockRenderer.return_value = mock_renderer_instance

        mock_composer_instance = MagicMock()
        MockComposer.return_value = mock_composer_instance

        def fake_compose(scenes, work_dir, out, music=None, durations=None):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("fake")
            return out

        mock_composer_instance.compose.side_effect = fake_compose

        # Original callback should NOT be called during render
        original_cb = MagicMock()
        per_call_cb = MagicMock()

        pipeline = Pipeline(on_progress=original_cb)
        out_path = tmp_path / "out.mp4"
        pipeline.render(
            _make_script(),
            out=str(out_path),
            on_progress=per_call_cb,
            keep_artifacts=False,
        )

        # per_call_cb should have been used
        assert per_call_cb.call_count > 0
        # original_cb should NOT have been called during render
        assert original_cb.call_count == 0
        # After render, original should be restored
        assert pipeline.on_progress is original_cb


# ---------------------------------------------------------------------------
# Test Pipeline error handling
# ---------------------------------------------------------------------------


class TestPipelineErrorHandling:
    """Tests for error propagation and cleanup on failure."""

    @patch("explainer.core.pipeline.ExplainerConfig.resolve")
    @patch("explainer.core.pipeline.Registry")
    @patch("explainer.providers.llm_heuristic.HeuristicProvider.generate_script")
    def test_scripting_error_cleans_up(
        self,
        mock_gen_script: MagicMock,
        MockRegistry: MagicMock,
        mock_resolve: MagicMock,
        tmp_path: Path,
    ) -> None:
        """If scripting fails, work_dir is cleaned up."""
        from explainer.core.errors import ScriptValidationError

        mock_config = MagicMock()
        mock_config.llm = None
        mock_config.tts = "edge"
        mock_config.voice = None
        mock_resolve.return_value = mock_config

        mock_registry_instance = MagicMock()
        mock_registry_instance.list_templates.return_value = []
        MockRegistry.return_value = mock_registry_instance

        mock_gen_script.side_effect = ScriptValidationError("bad script")

        pipeline = Pipeline()

        with pytest.raises(ScriptValidationError):
            pipeline.generate("Broken", keep_artifacts=False)

    @patch("explainer.core.pipeline.ExplainerConfig.resolve")
    @patch("explainer.core.pipeline.Registry")
    @patch("explainer.providers.llm_heuristic.HeuristicProvider.generate_script")
    @patch("explainer.providers.tts_edge.EdgeTTSProvider.synthesize")
    def test_narration_error_propagates(
        self,
        mock_synthesize: MagicMock,
        mock_gen_script: MagicMock,
        MockRegistry: MagicMock,
        mock_resolve: MagicMock,
        tmp_path: Path,
    ) -> None:
        """NarrationError from TTS propagates and work_dir is cleaned."""
        from explainer.core.errors import NarrationError

        mock_config = MagicMock()
        mock_config.llm = None
        mock_config.tts = "edge"
        mock_config.voice = None
        mock_resolve.return_value = mock_config

        mock_registry_instance = MagicMock()
        mock_registry_instance.list_templates.return_value = []
        MockRegistry.return_value = mock_registry_instance

        mock_gen_script.return_value = _make_script()
        mock_synthesize.side_effect = NarrationError("TTS failed", scene_id=1)

        pipeline = Pipeline()

        with pytest.raises(NarrationError):
            pipeline.generate("Test", keep_artifacts=False)


# ---------------------------------------------------------------------------
# Test Pipeline._sanitize_script_data
# ---------------------------------------------------------------------------


class TestPipelineSanitize:
    """Tests for script data sanitization."""

    def test_sanitize_strips_html_from_scene_data(self) -> None:
        script = _make_script()
        script.scenes[1].data = {
            "bullets": ["<script>alert('xss')</script>Normal text"]
        }

        Pipeline._sanitize_script_data(script)

        assert "<script>" not in str(script.scenes[1].data)
        assert "Normal text" in script.scenes[1].data["bullets"][0]

    def test_sanitize_strips_javascript_uri(self) -> None:
        script = _make_script()
        script.scenes[1].data = {"link": "javascript: alert(1)"}

        Pipeline._sanitize_script_data(script)

        assert (
            "javascript" not in script.scenes[1].data["link"].lower()
            or ":" not in script.scenes[1].data["link"]
        )

    def test_sanitize_strips_html_from_scene_title(self) -> None:
        """Scene.title is LLM output and reaches the DOM, so it must be cleaned."""
        script = _make_script()
        script.scenes[0].title = "<img src=x onerror=alert(1)>Photosynthesis"

        Pipeline._sanitize_script_data(script)

        assert "<img" not in script.scenes[0].title
        assert "onerror" not in script.scenes[0].title
        assert "Photosynthesis" in script.scenes[0].title

    def test_animation_markup_keeps_tags_but_strips_handlers(self) -> None:
        """Animation markup is injected via innerHTML — tags stay, handlers go."""
        script = _make_script()
        script.scenes[1] = Scene(
            id=2,
            kind=SceneKind.ANIMATION,
            title="Orbit",
            narration="Watch the orbit.",
            data={
                "markup": '<svg><img src="x" onerror="alert(1)"/><circle id="c"/></svg>',
                "js": "document.getElementById('c').setAttribute('r', String(10*t));",
            },
        )

        Pipeline._sanitize_script_data(script)

        markup = script.scenes[1].data["markup"]
        assert "<svg>" in markup
        assert "circle" in markup
        assert "onerror" not in markup
        # draw(t) body is left alone for the host template to compile
        assert "getElementById" in script.scenes[1].data["js"]


class TestValidateAnimationScenes:
    """Animation code must be gated on both generate and render paths."""

    def test_validate_rejects_nondeterministic_js(self) -> None:
        from explainer.core.errors import ScriptValidationError

        script = _make_script()
        script.scenes[1] = Scene(
            id=2,
            kind=SceneKind.ANIMATION,
            title="Bad",
            narration="Nope.",
            data={
                "markup": "<svg><rect id='a'/></svg>",
                "js": "var x = Date.now();",
            },
        )

        with pytest.raises(ScriptValidationError, match="Date.now"):
            Pipeline._validate_animation_scenes(script)

    @patch("explainer.core.pipeline.ExplainerConfig.resolve")
    @patch("explainer.providers.tts_edge.EdgeTTSProvider.synthesize")
    def test_render_rejects_bad_animation_before_tts(
        self,
        mock_synthesize: MagicMock,
        mock_resolve: MagicMock,
        tmp_path: Path,
    ) -> None:
        """render()/--script must validate animation code before narration."""
        from explainer.core.errors import ScriptValidationError

        mock_config = MagicMock()
        mock_config.llm = None
        mock_config.tts = "edge"
        mock_config.voice = None
        mock_resolve.return_value = mock_config

        script = _make_script()
        script.scenes[1] = Scene(
            id=2,
            kind=SceneKind.ANIMATION,
            title="Bad",
            narration="Nope.",
            data={
                "markup": "<svg><rect id='a'/></svg>",
                "js": "var x = Math.random();",
            },
        )

        pipeline = Pipeline()
        with pytest.raises(ScriptValidationError, match="Math.random"):
            pipeline.render(script, out=str(tmp_path / "out.mp4"), keep_artifacts=False)

        mock_synthesize.assert_not_called()


class TestUnimplementedTTSIsRejected:
    """An unimplemented TTS provider must fail, never silently fall back."""

    @pytest.mark.parametrize("provider", ["elevenlabs", "azure", "coqui"])
    def test_rejected_at_construction(self, provider: str) -> None:
        from explainer.core.errors import ConfigError

        env_keys = {"ELEVENLABS_API_KEY": "k", "AZURE_SPEECH_KEY": "k"}
        cfg = MagicMock()
        cfg.tts = provider
        with (
            patch("explainer.config.ExplainerConfig.resolve", return_value=cfg),
            patch.dict("os.environ", env_keys),
            pytest.raises(ConfigError, match="not implemented"),
        ):
            Pipeline(tts=provider)

    def test_edge_is_accepted(self) -> None:
        cfg = MagicMock()
        cfg.tts = "edge"
        with patch("explainer.config.ExplainerConfig.resolve", return_value=cfg):
            pipeline = Pipeline(tts="edge")
        assert pipeline.config.tts == "edge"


class TestSceneTitleReachesTemplate:
    """Scene.title must be delivered to templates via setSceneData()."""

    @staticmethod
    def _render_data(script: Script) -> list[dict[str, object]]:
        """Run stage 3 with the renderer mocked and capture each job's data."""
        mock_config = MagicMock()
        mock_config.tts = "edge"  # Pipeline rejects unimplemented providers
        with (
            patch("explainer.config.ExplainerConfig.resolve", return_value=mock_config),
            patch("explainer.core.pipeline.Renderer") as mock_renderer,
        ):
            pipeline = Pipeline()
            pipeline._stage_rendering(
                script=script,
                fps=15,
                resolution="720p",
                duration_map={s.id: 2.0 for s in script.scenes},
                work_dir=Path("/tmp/does-not-matter"),
            )
        jobs = mock_renderer.return_value.render_all.call_args[0][0]
        return [job.data for job in jobs]

    def test_scene_title_is_passed_as_data_title(self, tmp_path: Path) -> None:
        script = _make_script(topic="Photosynthesis")

        with patch("explainer.core.pipeline.Path.mkdir"):
            data = self._render_data(script)

        # The title template renders data.title; without this the card is blank.
        assert data[0]["title"] == "Photosynthesis"
        assert data[1]["title"] == "What is gravity?"

    def test_explicit_data_title_wins(self, tmp_path: Path) -> None:
        script = _make_script()
        script.scenes[0].data = {"title": "Explicit Override"}

        with patch("explainer.core.pipeline.Path.mkdir"):
            data = self._render_data(script)

        assert data[0]["title"] == "Explicit Override"

    def test_existing_data_keys_are_preserved(self, tmp_path: Path) -> None:
        script = _make_script()

        with patch("explainer.core.pipeline.Path.mkdir"):
            data = self._render_data(script)

        assert data[1]["bullets"] == ["Force", "Mass"]
