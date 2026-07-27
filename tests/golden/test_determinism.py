"""Determinism test: render the same template twice and assert SHA-256 match.

Validates Requirement 9.5 — identical inputs produce identical frame output.
Requires Playwright with Chromium installed. Marked @pytest.mark.golden.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from explainer.core.schema import Script
from tests.helpers import requires_chromium

pytestmark = [pytest.mark.golden]


@pytest.fixture
def title_template_html() -> Path:
    """Return the path to the bundled title template's index.html."""
    template_dir = (
        Path(__file__).parent.parent.parent / "explainer" / "templates" / "title"
    )
    html_path = template_dir / "index.html"
    if not html_path.exists():
        pytest.skip("Title template index.html not found")
    return html_path


def _render_frames(
    template_html: Path, scene_data: dict, style: dict, output_dir: Path
) -> list[Path]:
    """Render a template at t=0.0, 0.25, 0.5, 0.75, 1.0 and return frame paths."""
    from playwright.sync_api import sync_playwright

    time_steps = [0.0, 0.25, 0.5, 0.75, 1.0]
    frames: list[Path] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 720})

            # Block network
            page.route(
                "**/*",
                lambda route: (
                    route.continue_()
                    if route.request.url.startswith("file://")
                    else route.abort()
                ),
            )

            template_url = f"file://{template_html.resolve()}"
            page.goto(template_url)

            # Inject data
            page.evaluate(
                "([data, style]) => window.setSceneData(data, style)",
                [scene_data, style],
            )

            # Capture frames
            for t in time_steps:
                page.evaluate("(t) => window.renderFrame(t)", t)
                frame_path = output_dir / f"f_{t:.2f}.png"
                page.screenshot(path=str(frame_path))
                frames.append(frame_path)

        finally:
            browser.close()

    return frames


@requires_chromium()
def test_determinism_sha256_match(
    title_template_html: Path, golden_script_path: Path, work_dir: Path
):
    """Render the same fixture twice with identical inputs → SHA-256 must match.

    This validates the core determinism invariant: progress-driven rendering
    with network disabled produces pixel-identical output across runs.
    """
    script = Script.from_file(golden_script_path)
    title_scene = script.scenes[0]

    # First render pass
    pass1_dir = work_dir / "pass1"
    pass1_dir.mkdir()
    frames_pass1 = _render_frames(title_template_html, title_scene.data, {}, pass1_dir)

    # Second render pass
    pass2_dir = work_dir / "pass2"
    pass2_dir.mkdir()
    frames_pass2 = _render_frames(title_template_html, title_scene.data, {}, pass2_dir)

    # Assert same number of frames
    assert len(frames_pass1) == len(frames_pass2), (
        f"Frame count mismatch: pass1={len(frames_pass1)}, pass2={len(frames_pass2)}"
    )

    # Assert each frame is byte-identical (SHA-256 match)
    for f1, f2 in zip(frames_pass1, frames_pass2, strict=True):
        hash1 = hashlib.sha256(f1.read_bytes()).hexdigest()
        hash2 = hashlib.sha256(f2.read_bytes()).hexdigest()
        assert hash1 == hash2, (
            f"Determinism violation: {f1.name} differs between passes.\n"
            f"  Pass 1: {hash1}\n"
            f"  Pass 2: {hash2}\n"
            f"Templates must be pure functions of (data, t) with no side effects."
        )


@requires_chromium()
def test_determinism_multiple_time_steps(
    title_template_html: Path, golden_script_path: Path, work_dir: Path
):
    """Verify that rendering at the same t value always produces the same result.

    Renders t=0.5 three times in a row and verifies all outputs match.
    """
    from playwright.sync_api import sync_playwright

    script = Script.from_file(golden_script_path)
    title_scene = script.scenes[0]

    frames_dir = work_dir / "repeat_test"
    frames_dir.mkdir()

    hashes: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 720})

            page.route(
                "**/*",
                lambda route: (
                    route.continue_()
                    if route.request.url.startswith("file://")
                    else route.abort()
                ),
            )

            template_url = f"file://{title_template_html.resolve()}"
            page.goto(template_url)

            page.evaluate(
                "([data, style]) => window.setSceneData(data, style)",
                [title_scene.data, {}],
            )

            # Render t=0.5 three times
            for i in range(3):
                page.evaluate("(t) => window.renderFrame(t)", 0.5)
                frame_path = frames_dir / f"repeat_{i}.png"
                page.screenshot(path=str(frame_path))
                hashes.append(hashlib.sha256(frame_path.read_bytes()).hexdigest())

        finally:
            browser.close()

    # All three renders of the same t should be identical
    assert len(set(hashes)) == 1, (
        f"Same t=0.5 produced different outputs across 3 renders:\n"
        f"  Hashes: {hashes}\n"
        f"renderFrame must be a pure function of t."
    )


@pytest.fixture
def animation_template_html() -> Path:
    """Return the path to the bundled animation host template's index.html."""
    html_path = (
        Path(__file__).parent.parent.parent
        / "explainer"
        / "templates"
        / "animation"
        / "index.html"
    )
    if not html_path.exists():
        pytest.skip("Animation template index.html not found")
    return html_path


# Stands in for model-authored code: sequenced purely off t via the host helpers.
_ANIMATION_SCENE_DATA = {
    "markup": (
        "<svg viewBox='0 0 900 400' width='900' height='400'>"
        "<rect id='box' x='40' y='160' width='160' height='80' rx='10' "
        "fill='none' stroke='#4fc3f7' stroke-width='3' opacity='0'/>"
        "<line id='arrow' x1='210' y1='200' x2='210' y2='200' "
        "stroke='#4fc3f7' stroke-width='4'/>"
        "</svg>"
    ),
    "js": (
        "document.getElementById('box').setAttribute('opacity', ease(seg(t, 0, 0.4)));"
        "document.getElementById('arrow').setAttribute("
        "'x2', String(lerp(210, 820, ease(seg(t, 0.4, 1)))));"
    ),
    "caption": "Deterministic model-authored scene",
}


@requires_chromium()
def test_animation_template_is_deterministic(
    animation_template_html: Path, tmp_path: Path
) -> None:
    """Model-authored draw(t) code must render byte-identically across runs."""
    style = {"bg": "#0d1b2a", "accent": "#4fc3f7", "font": "sans-serif"}

    pass1 = _render_frames(
        animation_template_html, _ANIMATION_SCENE_DATA, style, tmp_path / "pass1"
    )
    pass2 = _render_frames(
        animation_template_html, _ANIMATION_SCENE_DATA, style, tmp_path / "pass2"
    )

    assert len(pass1) == len(pass2)
    for f1, f2 in zip(pass1, pass2, strict=True):
        h1 = hashlib.sha256(f1.read_bytes()).hexdigest()
        h2 = hashlib.sha256(f2.read_bytes()).hexdigest()
        assert h1 == h2, f"Animation host is non-deterministic at {f1.name}"


@requires_chromium()
def test_animation_frames_differ_over_t(
    animation_template_html: Path, tmp_path: Path
) -> None:
    """draw(t) must actually use t — identical frames would mean a static scene."""
    frames = _render_frames(
        animation_template_html, _ANIMATION_SCENE_DATA, {"bg": "#0d1b2a"}, tmp_path
    )
    hashes = {hashlib.sha256(f.read_bytes()).hexdigest() for f in frames}
    assert len(hashes) > 1, "every frame identical — draw(t) ignored t"
