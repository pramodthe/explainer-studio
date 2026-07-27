"""Unit tests for the explainer exception hierarchy."""

import pytest

from explainer.core.errors import (
    CompositionError,
    ConfigError,
    ExplainerError,
    NarrationError,
    RenderError,
    ScriptValidationError,
)


class TestExplainerError:
    """Tests for the base ExplainerError class."""

    def test_stores_message_and_stage(self):
        err = ExplainerError("something broke", stage="rendering")
        assert err.message == "something broke"
        assert err.stage == "rendering"

    def test_default_stage_is_unknown(self):
        err = ExplainerError("generic error")
        assert err.stage == "unknown"

    def test_str_includes_stage_and_message(self):
        err = ExplainerError("oops", stage="composing")
        assert str(err) == "[composing] oops"

    def test_is_exception_subclass(self):
        err = ExplainerError("test")
        assert isinstance(err, Exception)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(ExplainerError, match="fail"):
            raise ExplainerError("fail", stage="test")


class TestScriptValidationError:
    """Tests for ScriptValidationError."""

    def test_stage_is_scripting(self):
        err = ScriptValidationError("invalid schema")
        assert err.stage == "scripting"

    def test_stores_message(self):
        err = ScriptValidationError("missing title scene")
        assert err.message == "missing title scene"

    def test_str_representation(self):
        err = ScriptValidationError("bad output")
        assert str(err) == "[scripting] bad output"

    def test_inherits_from_base(self):
        err = ScriptValidationError("test")
        assert isinstance(err, ExplainerError)


class TestNarrationError:
    """Tests for NarrationError."""

    def test_stage_is_narrating(self):
        err = NarrationError("tts timeout", scene_id=2)
        assert err.stage == "narrating"

    def test_stores_scene_id(self):
        err = NarrationError("failed", scene_id=3)
        assert err.scene_id == 3

    def test_str_includes_scene_id(self):
        err = NarrationError("timeout after 30s", scene_id=1)
        assert str(err) == "[narrating] scene 1: timeout after 30s"

    def test_inherits_from_base(self):
        err = NarrationError("test", scene_id=0)
        assert isinstance(err, ExplainerError)


class TestRenderError:
    """Tests for RenderError."""

    def test_stage_is_rendering(self):
        err = RenderError("crash", scene_id=1)
        assert err.stage == "rendering"

    def test_stores_scene_id_and_frame_index(self):
        err = RenderError("js error", scene_id=2, frame_index=45)
        assert err.scene_id == 2
        assert err.frame_index == 45

    def test_optional_scene_id_and_frame_index(self):
        err = RenderError("chromium crash")
        assert err.scene_id is None
        assert err.frame_index is None

    def test_str_with_all_fields(self):
        err = RenderError("timeout", scene_id=3, frame_index=120)
        assert str(err) == "[rendering] scene 3 frame 120 timeout"

    def test_str_with_scene_only(self):
        err = RenderError("crash", scene_id=2)
        assert str(err) == "[rendering] scene 2 crash"

    def test_str_with_no_context(self):
        err = RenderError("chromium died")
        assert str(err) == "[rendering] chromium died"

    def test_inherits_from_base(self):
        err = RenderError("test")
        assert isinstance(err, ExplainerError)


class TestCompositionError:
    """Tests for CompositionError."""

    def test_stage_is_composing(self):
        err = CompositionError("encode failed", ffmpeg_stderr="error line")
        assert err.stage == "composing"

    def test_stores_ffmpeg_stderr(self):
        err = CompositionError("concat failed", ffmpeg_stderr="some output")
        assert err.ffmpeg_stderr == "some output"

    def test_truncates_stderr_to_1024_chars(self):
        long_stderr = "x" * 2000
        err = CompositionError("failed", ffmpeg_stderr=long_stderr)
        assert len(err.ffmpeg_stderr) == 1024

    def test_str_includes_stderr(self):
        err = CompositionError("encoding error", ffmpeg_stderr="bad codec")
        result = str(err)
        assert "[composing]" in result
        assert "encoding error" in result
        assert "bad codec" in result

    def test_inherits_from_base(self):
        err = CompositionError("test", ffmpeg_stderr="")
        assert isinstance(err, ExplainerError)


class TestConfigError:
    """Tests for ConfigError."""

    def test_stage_is_config(self):
        err = ConfigError("missing OPENAI_API_KEY")
        assert err.stage == "config"

    def test_stores_message(self):
        err = ConfigError("ffmpeg not found on PATH")
        assert err.message == "ffmpeg not found on PATH"

    def test_str_representation(self):
        err = ConfigError("set EXPLAINER_TTS env var")
        assert str(err) == "[config] set EXPLAINER_TTS env var"

    def test_inherits_from_base(self):
        err = ConfigError("test")
        assert isinstance(err, ExplainerError)


class TestExceptionCatching:
    """Test that exceptions can be caught at different hierarchy levels."""

    def test_catch_all_via_base_class(self):
        errors = [
            ScriptValidationError("a"),
            NarrationError("b", scene_id=1),
            RenderError("c", scene_id=1, frame_index=0),
            CompositionError("d", ffmpeg_stderr="e"),
            ConfigError("f"),
        ]
        for err in errors:
            with pytest.raises(ExplainerError):
                raise err

    def test_each_has_distinct_stage(self):
        stages = {
            ScriptValidationError("a").stage,
            NarrationError("b", scene_id=1).stage,
            RenderError("c").stage,
            CompositionError("d", ffmpeg_stderr="").stage,
            ConfigError("f").stage,
        }
        assert stages == {"scripting", "narrating", "rendering", "composing", "config"}
