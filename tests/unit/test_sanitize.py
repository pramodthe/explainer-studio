"""Unit tests for explainer.core.sanitize module."""

from __future__ import annotations

import logging

import pytest

from explainer.core.sanitize import sanitize_scene_data


class TestPlainStrings:
    """Plain strings pass through unchanged."""

    def test_plain_text(self):
        assert sanitize_scene_data("Hello world") == "Hello world"

    def test_empty_string(self):
        assert sanitize_scene_data("") == ""

    def test_string_with_special_chars(self):
        text = "a² + b² = c² (Pythagorean theorem)"
        assert sanitize_scene_data(text) == text

    def test_string_with_angle_brackets_in_math(self):
        # "x > 5" should not be mangled (no closing >)
        text = "if x > 5 then y = 10"
        assert sanitize_scene_data(text) == text


class TestHTMLTagStripping:
    """HTML tags are stripped from string values."""

    def test_script_tag(self):
        result = sanitize_scene_data("<script>alert('xss')</script>")
        assert "<script>" not in result
        assert "</script>" not in result
        assert "alert('xss')" in result

    def test_img_tag(self):
        result = sanitize_scene_data('<img src="x" onerror="alert(1)">')
        assert "<img" not in result
        assert ">" not in result or result == ""

    def test_div_tags(self):
        result = sanitize_scene_data("<div>content</div>")
        assert result == "content"

    def test_self_closing_tag(self):
        result = sanitize_scene_data("<br/>")
        assert result == ""

    def test_nested_tags(self):
        result = sanitize_scene_data("<b><i>bold italic</i></b>")
        assert result == "bold italic"


class TestEventHandlerRemoval:
    """Event handler attributes are stripped."""

    def test_onclick(self):
        result = sanitize_scene_data('onclick="alert(1)"')
        assert "onclick" not in result

    def test_onerror(self):
        result = sanitize_scene_data("onerror='malicious()'")
        assert "onerror" not in result

    def test_onload(self):
        result = sanitize_scene_data("onload=init()")
        assert "onload" not in result

    def test_onmouseover(self):
        result = sanitize_scene_data('onmouseover="track()"')
        assert "onmouseover" not in result

    def test_mixed_content_with_handler(self):
        result = sanitize_scene_data('Click here onclick="steal()" for more')
        assert "onclick" not in result
        assert "Click here" in result
        assert "for more" in result


class TestJavascriptURIRemoval:
    """javascript: URIs are stripped."""

    def test_basic_javascript_uri(self):
        result = sanitize_scene_data("javascript:alert(1)")
        assert "javascript:" not in result.lower()

    def test_javascript_uri_with_spaces(self):
        result = sanitize_scene_data("javascript :void(0)")
        assert (
            "javascript" not in result.lower() or "javascript :" not in result.lower()
        )

    def test_javascript_uri_case_insensitive(self):
        result = sanitize_scene_data("JavaScript:alert('xss')")
        assert "javascript:" not in result.lower()

    def test_javascript_uri_in_context(self):
        result = sanitize_scene_data("Visit javascript:void(0) link")
        assert "javascript:" not in result.lower()


class TestDangerousDataURIRemoval:
    """Script-bearing data: URIs are stripped."""

    def test_data_text_html(self):
        result = sanitize_scene_data("data:text/html,<script>alert(1)</script>")
        assert "data:text/html" not in result.lower()

    def test_data_application_javascript(self):
        result = sanitize_scene_data("data:application/javascript,alert(1)")
        assert "data:application/javascript" not in result.lower()

    def test_data_text_javascript(self):
        result = sanitize_scene_data("data:text/javascript,code()")
        assert "data:text/javascript" not in result.lower()

    def test_data_application_ecmascript(self):
        result = sanitize_scene_data("data:application/ecmascript,code()")
        assert "data:application/ecmascript" not in result.lower()


class TestSafeDataURIs:
    """Safe data: URIs (images, etc.) pass through unchanged."""

    def test_data_image_png(self):
        uri = "data:image/png;base64,iVBORw0KGgo="
        assert sanitize_scene_data(uri) == uri

    def test_data_image_svg(self):
        uri = "data:image/svg+xml;base64,PHN2Zz4="
        assert sanitize_scene_data(uri) == uri

    def test_data_image_jpeg(self):
        uri = "data:image/jpeg;base64,/9j/4AAQ="
        assert sanitize_scene_data(uri) == uri

    def test_data_font_woff2(self):
        uri = "data:font/woff2;base64,d09GMg=="
        assert sanitize_scene_data(uri) == uri


class TestRecursiveProcessing:
    """Dicts and lists are processed recursively."""

    def test_dict_with_clean_values(self):
        data = {"title": "Hello", "count": 5}
        assert sanitize_scene_data(data) == {"title": "Hello", "count": 5}

    def test_dict_with_dirty_values(self):
        data = {"title": "<script>bad</script>Safe Title"}
        result = sanitize_scene_data(data)
        assert "<script>" not in result["title"]
        assert "Safe Title" in result["title"]

    def test_list_of_strings(self):
        data = ["clean", "<b>bold</b>", "also clean"]
        result = sanitize_scene_data(data)
        assert result == ["clean", "bold", "also clean"]

    def test_nested_dict_in_list(self):
        data = [{"text": "<script>x</script>safe"}]
        result = sanitize_scene_data(data)
        assert "<script>" not in result[0]["text"]
        assert "safe" in result[0]["text"]

    def test_deeply_nested(self):
        data = {"level1": {"level2": {"level3": ["<div>deep</div>"]}}}
        result = sanitize_scene_data(data)
        assert result == {"level1": {"level2": {"level3": ["deep"]}}}

    def test_complex_scene_data(self):
        """Simulate realistic scene data structure."""
        data = {
            "bullets": [
                "Photosynthesis converts CO₂ to O₂",
                "<script>steal()</script>Normal point",
            ],
            "diagram": {
                "type": "cycle",
                "labels": ["Sun", "Plant", 'O₂ onclick="bad()"'],
            },
        }
        result = sanitize_scene_data(data)
        assert result["bullets"][0] == "Photosynthesis converts CO₂ to O₂"
        assert "<script>" not in result["bullets"][1]
        assert "Normal point" in result["bullets"][1]
        assert "onclick" not in result["diagram"]["labels"][2]


class TestNonStringValues:
    """Non-string scalars pass through unchanged."""

    def test_integer(self):
        assert sanitize_scene_data(42) == 42

    def test_float(self):
        assert sanitize_scene_data(3.14) == 3.14

    def test_boolean_true(self):
        assert sanitize_scene_data(True) is True

    def test_boolean_false(self):
        assert sanitize_scene_data(False) is False

    def test_none(self):
        assert sanitize_scene_data(None) is None

    def test_dict_with_mixed_types(self):
        data = {
            "name": "test",
            "count": 10,
            "active": True,
            "extra": None,
            "ratio": 0.5,
        }
        assert sanitize_scene_data(data) == data


class TestLoggingWarnings:
    """Warnings are logged when content is removed."""

    def test_html_tag_logs_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="explainer.core.sanitize"):
            sanitize_scene_data("<script>bad</script>")
        assert "Stripped HTML tags" in caplog.text

    def test_event_handler_logs_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="explainer.core.sanitize"):
            sanitize_scene_data('onclick="evil()"')
        assert "Stripped event-handler" in caplog.text

    def test_javascript_uri_logs_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="explainer.core.sanitize"):
            sanitize_scene_data("javascript:void(0)")
        assert "javascript" in caplog.text.lower()

    def test_dangerous_data_uri_logs_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="explainer.core.sanitize"):
            sanitize_scene_data("data:text/html,<h1>hi</h1>")
        assert "data:" in caplog.text.lower() or "data" in caplog.text.lower()

    def test_clean_string_no_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="explainer.core.sanitize"):
            sanitize_scene_data("Perfectly clean string")
        assert caplog.text == ""

    def test_non_string_no_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="explainer.core.sanitize"):
            sanitize_scene_data({"count": 42, "active": True})
        assert caplog.text == ""


class TestAnimationCodeValidation:
    """Model-authored animation code must stay a pure function of t."""

    def test_clean_code_passes(self):
        from explainer.core.sanitize import validate_animation_code

        data = {
            "markup": "<svg><rect id='a'/></svg>",
            "js": "document.getElementById('a').setAttribute('opacity', ease(seg(t,0,.5)));",
            "css": "#a { fill: none; }",
        }
        assert validate_animation_code(data) == []

    @pytest.mark.parametrize(
        "field,code",
        [
            ("js", "var x = Date.now();"),
            ("js", "var x = new Date();"),
            ("js", "var x = Math.random();"),
            ("js", "setTimeout(fn, 10);"),
            ("js", "setInterval(fn, 10);"),
            ("js", "requestAnimationFrame(fn);"),
            ("js", "fetch('/data.json');"),
            ("js", "new XMLHttpRequest();"),
            ("markup", "<img src='https://example.com/a.png'>"),
            ("markup", '<img src=x onerror="alert(1)">'),
            ("markup", '<a href="javascript:alert(1)">x</a>'),
            ("markup", "<script>alert(1)</script>"),
            ("css", "#a { transition: all 0.3s; }"),
            ("css", "@keyframes spin { from {} to {} }"),
        ],
    )
    def test_nondeterministic_code_rejected(self, field, code):
        from explainer.core.sanitize import validate_animation_code

        violations = validate_animation_code({field: code})
        assert violations, f"{field}={code!r} should have been rejected"
        assert all(v.startswith(field) for v in violations)

    def test_non_string_fields_ignored(self):
        from explainer.core.sanitize import validate_animation_code

        assert validate_animation_code({"js": None, "markup": 42}) == []


class TestSanitizeAnimationMarkup:
    """Animation markup keeps tags but loses XSS vectors."""

    def test_preserves_svg_tags(self):
        from explainer.core.sanitize import sanitize_animation_markup

        markup = "<svg><rect id='a' width='10'/></svg>"
        assert sanitize_animation_markup(markup) == markup

    def test_strips_event_handlers(self):
        from explainer.core.sanitize import sanitize_animation_markup

        result = sanitize_animation_markup('<img src="x" onerror="alert(1)">')
        assert "onerror" not in result
        assert "<img" in result

    def test_strips_javascript_uri(self):
        from explainer.core.sanitize import sanitize_animation_markup

        result = sanitize_animation_markup('<a href="javascript:alert(1)">x</a>')
        assert "javascript" not in result.lower() or ":" not in result
        assert "<a" in result

    def test_strips_script_blocks(self):
        from explainer.core.sanitize import sanitize_animation_markup

        result = sanitize_animation_markup(
            "<svg></svg><script>alert(1)</script><div id='ok'/>"
        )
        assert "<script" not in result.lower()
        assert "<svg>" in result
        assert "id='ok'" in result
