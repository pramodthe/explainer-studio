"""Data sanitization for LLM-generated scene data.

Strips potentially dangerous content from string values before
they are injected into template DOM:
- HTML tags (e.g. <script>, <img onerror=...>)
- Event-handler attributes (onclick, onerror, onload, etc.)
- javascript: URIs
- Script-bearing data: URIs (text/html, application/javascript, etc.)

Animation scenes keep HTML/SVG tags in ``markup`` (they are the stage
content) but still strip handlers / javascript: / dangerous data: URIs
via :func:`sanitize_animation_markup`, and reject the same constructs
(plus non-deterministic APIs) in :func:`validate_animation_code`.

Logs a warning whenever content is removed.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Pattern to match HTML tags (including self-closing)
_HTML_TAG_RE = re.compile(r"<[^>]+>", re.IGNORECASE | re.DOTALL)

# Pattern to match event-handler attributes (on* = ...)
# Matches patterns like: onclick="...", onerror='...', onload=handler
_EVENT_HANDLER_RE = re.compile(
    r"""\bon[a-z]+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]*)""",
    re.IGNORECASE,
)

# Pattern to match javascript: URIs (with optional whitespace/encoding tricks)
_JAVASCRIPT_URI_RE = re.compile(
    r"""javascript\s*:""",
    re.IGNORECASE,
)

# Pattern to match dangerous data: URIs (text/html, application/javascript, etc.)
# Safe data: URIs (e.g. data:image/png) are NOT matched.
_DANGEROUS_DATA_URI_RE = re.compile(
    r"""data\s*:\s*(?:text/html|application/javascript|application/x-javascript|text/javascript|application/ecmascript|text/ecmascript)""",
    re.IGNORECASE,
)

# Full <script>...</script> blocks (and a lone opening tag) in animation markup.
_SCRIPT_BLOCK_RE = re.compile(
    r"<script\b[^>]*>.*?</script\s*>|<script\b[^>]*/?>",
    re.IGNORECASE | re.DOTALL,
)


# Fields of an "animation" scene that carry model-authored code. Tags in
# ``markup`` must survive (they are the stage content); handlers / URIs are
# stripped by sanitize_animation_markup(), and all three fields are checked
# by validate_animation_code().
ANIMATION_CODE_FIELDS: frozenset[str] = frozenset({"markup", "css", "js"})

# Constructs that break the "renderFrame(t) is a pure function of t" invariant,
# reach the network, or inject executable markup outside draw(t). The renderer
# steps t from 0 to 1 and screenshots each frame, so anything time- or
# randomness-dependent produces a different video on every run. Markup is
# injected via innerHTML, so event handlers and script URIs must also fail.
_FORBIDDEN_CODE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bDate\s*\.\s*now\b", "Date.now() — frames must depend only on t"),
    (r"\bnew\s+Date\b", "new Date() — frames must depend only on t"),
    (r"\bperformance\s*\.\s*now\b", "performance.now() — use t instead"),
    (r"\bMath\s*\.\s*random\b", "Math.random() — output must be reproducible"),
    (r"\bcrypto\s*\.\s*getRandomValues\b", "crypto.getRandomValues()"),
    (
        r"\brequestAnimationFrame\b",
        "requestAnimationFrame — rendering is not real-time",
    ),
    (r"\bsetTimeout\b", "setTimeout — rendering is not real-time"),
    (r"\bsetInterval\b", "setInterval — rendering is not real-time"),
    (r"\bfetch\s*\(", "fetch() — the page has no network access"),
    (r"\bXMLHttpRequest\b", "XMLHttpRequest — the page has no network access"),
    (r"\bWebSocket\b", "WebSocket — the page has no network access"),
    (r"\bimportScripts\b", "importScripts — external code is not available"),
    (r"""(?:src|href)\s*=\s*["']?\s*(?:https?:)?//""", "external URL reference"),
    (
        r"@(?:keyframes|import)\b",
        "CSS @keyframes/@import — motion must come from draw(t)",
    ),
    (r"\btransition\s*:", "CSS transition — motion must come from draw(t)"),
    (r"\banimation\s*:", "CSS animation — motion must come from draw(t)"),
    (
        r"\bon[a-z]+\s*=",
        "event-handler attribute — use draw(t) for behavior, not markup handlers",
    ),
    (r"javascript\s*:", "javascript: URI"),
    (
        r"data\s*:\s*(?:text/html|application/javascript|application/x-javascript|"
        r"text/javascript|application/ecmascript|text/ecmascript)",
        "script-bearing data: URI",
    ),
    (r"<script\b", "<script> tag — use draw(t) for behavior"),
)

_COMPILED_FORBIDDEN = tuple(
    (re.compile(pattern, re.IGNORECASE), reason)
    for pattern, reason in _FORBIDDEN_CODE_PATTERNS
)


def validate_animation_code(data: dict[str, Any]) -> list[str]:
    """Check model-authored animation code for unsafe / non-deterministic constructs.

    Args:
        data: An animation scene's `data` object.

    Returns:
        A list of human-readable violations, empty if the code is acceptable.
        The messages are fed back to the LLM on retry, so they name both the
        construct and why it is rejected.
    """
    violations: list[str] = []
    for field in sorted(ANIMATION_CODE_FIELDS):
        value = data.get(field)
        if not isinstance(value, str):
            continue
        for pattern, reason in _COMPILED_FORBIDDEN:
            if pattern.search(value):
                violations.append(f"{field}: forbidden {reason}")
    return violations


def _strip_uri_and_handler_threats(value: str) -> str:
    """Strip event handlers and dangerous URIs, logging when content is removed."""
    handlers = _EVENT_HANDLER_RE.findall(value)
    if handlers:
        value = _EVENT_HANDLER_RE.sub("", value)
        logger.warning(
            "Stripped event-handler attributes from scene data: %s",
            ", ".join(handlers[:5]),
        )

    js_uris = _JAVASCRIPT_URI_RE.findall(value)
    if js_uris:
        value = _JAVASCRIPT_URI_RE.sub("", value)
        logger.warning(
            "Stripped javascript: URI(s) from scene data (%d occurrence(s))",
            len(js_uris),
        )

    data_uris = _DANGEROUS_DATA_URI_RE.findall(value)
    if data_uris:
        value = _DANGEROUS_DATA_URI_RE.sub("", value)
        logger.warning(
            "Stripped dangerous data: URI(s) from scene data: %s",
            ", ".join(data_uris[:5]),
        )

    return value


def sanitize_animation_markup(value: str) -> str:
    """Sanitize animation ``markup`` while preserving HTML/SVG tags.

    Unlike :func:`sanitize_scene_data`, tags are kept because they are the
    stage content injected via ``innerHTML``. Event-handler attributes,
    ``javascript:`` URIs, script-bearing ``data:`` URIs, and ``<script>``
    blocks are still removed.

    Args:
        value: Raw model-authored markup for the animation stage.

    Returns:
        Markup safe to inject via ``innerHTML``.
    """
    scripts = _SCRIPT_BLOCK_RE.findall(value)
    if scripts:
        value = _SCRIPT_BLOCK_RE.sub("", value)
        logger.warning(
            "Stripped <script> block(s) from animation markup (%d occurrence(s))",
            len(scripts),
        )
    return _strip_uri_and_handler_threats(value)


def _sanitize_string(value: str) -> str:
    """Sanitize a single string value, logging warnings on removal."""
    # Strip HTML tags
    html_tags = _HTML_TAG_RE.findall(value)
    if html_tags:
        value = _HTML_TAG_RE.sub("", value)
        logger.warning(
            "Stripped HTML tags from scene data: %s",
            ", ".join(html_tags[:5]),  # limit logged items
        )

    return _strip_uri_and_handler_threats(value)


def sanitize_scene_data(data: Any) -> Any:
    """Recursively sanitize scene data.

    Processes dicts, lists, and strings. Non-string scalars (int, float,
    bool, None) pass through unchanged.

    Args:
        data: The scene data structure (typically a dict from Script.scenes[].data).

    Returns:
        The sanitized data with the same structure but cleaned string values.
    """
    if isinstance(data, str):
        return _sanitize_string(data)
    elif isinstance(data, dict):
        return {key: sanitize_scene_data(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [sanitize_scene_data(item) for item in data]
    else:
        # int, float, bool, None — pass through unchanged
        return data
