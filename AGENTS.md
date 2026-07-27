# AGENTS.md — Explainer Studio

## Project overview

Explainer Studio (`explainer-studio` on PyPI) is an open-source Python package that
generates short (30–90s), narrated, animated educational explainer videos (MP4) from a
single topic string. It ships as both a CLI tool (`explainer`) and a Python library
(`from explainer import Pipeline, Script`).

Core thesis: generative video models hallucinate facts and equations, so motion graphics
are rendered **deterministically** — self-contained HTML/SVG templates driven by a
progress function `t ∈ [0,1]` — making every visual correct by construction. The LLM
chooses and fills templates; for the six fixed templates it **never writes rendering
code**. The one exception is the `animation` scene kind, where the model authors
markup/CSS/JS inside a tightly validated sandbox contract (see below).

The repository contains the implemented package (v0.1.0). Formal specs live in
`.kiro/specs/explainer-studio/` (`requirements.md`, `design.md`, `tasks.md` — EARS-style
requirements with per-task requirement traceability).

## Repository layout

```
explainer/                 the Python package (hatchling build, pyproject.toml)
  __init__.py              lazy public API: Pipeline, Script, Scene, SceneKind
  cli.py                   typer CLI: generate / doctor / init / templates / voices
  config.py                ExplainerConfig: CLI args > env vars > config file > defaults
  core/
    schema.py              SceneKind enum (7 kinds), Scene & Script pydantic models
    errors.py              typed exception hierarchy, one class per pipeline stage
    registry.py            template discovery (bundled → user dir → entry points)
    pipeline.py            Pipeline orchestrator (4 stages, progress events, cleanup)
    renderer.py            Playwright/Chromium frame capture, parallel per scene
    composer.py            FFmpeg segment encoding + crossfade join + music ducking
    sanitize.py            HTML/URI sanitizer + animation-code determinism validator
  providers/
    llm_base.py            LLMProvider protocol + ScriptRequest/TemplateInfo models
    llm_litellm.py         any model via litellm (needs API key, one validation retry)
    llm_heuristic.py       offline zero-config fallback (fixed 4-scene structure)
    tts_base.py            TTSProvider protocol + Voice model
    tts_edge.py            edge-tts (default, free, no API key, 300+ voices)
    tts_openai.py          OpenAI gpt-4o-mini-tts (needs OPENAI_API_KEY, [openai] extra)
    tts_{elevenlabs,azure}.py   reserved stubs — constructors raise ImportError
  prompts/script_system.md system prompt for LLM script generation
  templates/<kind>/        7 bundled templates: title, concept, steps, compare, chart,
                           takeaway, animation — each: __init__.py (get_path()),
                           template.json (metadata + JSON Schema), index.html,
                           preview.png (all except animation)
tests/
  unit/                    fast tests, no external deps (10 files)
  golden/                  template render + determinism tests (need Chromium)
  e2e/                     full-pipeline test (needs FFmpeg; Chromium optional)
  fixtures/golden_script.json
  conftest.py, helpers.py  mock TTS, silent-MP3 generator, skip helpers
docs/                      MkDocs (Material) site: quickstart, cli, api, templates,
                           providers; config in docs/mkdocs.yml
examples/                  basic_usage.py, photosynthesis_script.json,
                           transformer_script.json
voice_samples/             sample MP3s of a few narration voices (reference only;
                           not read by the package)
.claude/skills/            explainer-studio/SKILL.md — playbook for coding agents
.github/workflows/         ci.yml (lint, unit, golden, e2e), publish.yml (PyPI)
llms.txt                   machine-readable project summary + canonical source links
.env.example               every environment variable the package reads
.kiro/specs/               formal product spec (requirements/design/tasks)
```

Licensed MIT (`LICENSE`). Keep `README.md`, `llms.txt`, and `docs/` consistent when you
change public behaviour — all three describe the same surface.

## Tech stack and runtime requirements

- Python ≥ 3.10 (CI tests 3.10/3.11/3.12); pydantic v2, typer + rich (CLI),
  Playwright (headless Chromium), edge-tts, litellm, jsonschema (direct dependency,
  used by `Script.validate_with_templates()`), tomli (Python < 3.11).
- System tools on PATH: `ffmpeg` and `ffprobe` (composition + audio probing).
- Chromium installed via `playwright install chromium`.
- Cross-platform: Linux and macOS natively; Windows via WSL only.
- Optional extras: `pip install explainer-studio[elevenlabs|azure|openai|dev]`.

## Setup and commands

```bash
# Setup (a .venv already exists in this repo)
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
explainer doctor                   # verifies ffmpeg/ffprobe, Chromium, config

# Run
explainer generate "photosynthesis"            # zero-config: heuristic LLM + edge-tts
explainer generate "gravity" --script my.json  # skip LLM with a pre-written script
explainer templates list                       # discovered templates
explainer templates preview concept            # renders t=0/0.5/1.0 PNGs
explainer init                                 # writes ~/.explainer/config.toml

# Tests
pytest -m unit                   # unit tests (fast, no external deps)
pytest -m golden                 # template render + determinism; needs Chromium
pytest -m e2e                    # pipeline + FFmpeg compose; needs FFmpeg
pytest -m "not golden and not e2e"   # everything runnable without a browser

# Lint / type check
ruff check .
ruff format --check .
mypy explainer/                  # strict = true is set in pyproject.toml

```

Markers are applied automatically by directory in `tests/conftest.py`
(`pytest_collection_modifyitems`), so a new file under `tests/unit/` is picked up by
`pytest -m unit` without declaring `pytestmark` itself.

## Architecture: the four-stage pipeline

Orchestrated by `Pipeline` (`explainer/core/pipeline.py`). `generate()` runs all four
stages; `render(script)` skips stage 1. Work happens in a temp dir (`explainer-*`),
removed unless `keep_artifacts=True`. Progress flows through an `on_progress` callback
receiving `ProgressEvent(stage, pct, message)`; stages are
`scripting → narrating → rendering → composing → done`.

1. **Scripting** — an LLM provider returns a validated `Script` (`core/schema.py`):
   3–6 scenes, first must be `title`, last must be `takeaway`. Each `Scene` has a
   `kind` (`title|concept|steps|compare|chart|takeaway|animation`), `narration`
   (~400-char soft limit, warns only), and template-specific `data`.
   `Script.validate_with_templates()` checks each scene's `data` against the
   template's JSON Schema (Draft 7, via the `jsonschema` dependency). After
   generation, every `animation` scene's code is checked by
   `validate_animation_code()`; violations raise `ScriptValidationError` before any
   TTS spend. The litellm provider retries once with the validation errors fed back.
2. **Narration (TTS)** — one MP3 per scene. **Audio-first timing is a hard invariant**:
   scene duration = audio duration + 0.4s tail pad (`_TAIL_PAD_SECONDS`); narration
   length defines scene length, never the reverse. Duration is measured with ffprobe.
   Only `edge` and `openai` TTS providers are implemented (`IMPLEMENTED_TTS` in
   `config.py`); requesting anything else fails loudly at `Pipeline` construction —
   no silent provider substitution.
3. **Rendering** (`core/renderer.py`) — each scene renders in its own headless
   Chromium via Playwright, in parallel through `ProcessPoolExecutor`
   (default `min(4, cpu_count)` workers). All non-`file://` network requests are
   aborted via route interception. The page's `window.setSceneData(data, style)` is
   called once, then `window.renderFrame(t)` per frame stepping t from 0→1,
   screenshotting `f{NNNN}.png`. Templates lay out on a fixed 1280×720 stage; higher
   resolutions scale the device pixel ratio, not the viewport. Playwright's
   `page.evaluate()` takes no per-call timeout —
   `page.set_default_timeout(_PAGE_TIMEOUT_MS)` bounds navigation and screenshots
   instead. Scene data passes through `core/sanitize.py` before injection (except
   animation code fields, which are validated at scripting time instead).
   `resume=True` skips scenes whose frames already exist (crash-resume).
4. **Composition** (`core/composer.py`) — FFmpeg encodes each scene's frames + audio
   to a segment MP4 (`libx264`, `yuv420p`, AAC, `-shortest`, metadata stripped), then
   joins segments with a 0.5s crossfade (`xfade` + `acrossfade`; segment durations
   probed with ffprobe, fade clamped to half the shortest scene). `Composer(transition=0)`
   falls back to the concat demuxer (`-c copy`) for hard cuts. Optional background
   music is ducked to −18dB under narration via the `amix` filter.

Errors are typed per stage (`core/errors.py`): `ScriptValidationError`,
`NarrationError`, `RenderError`, `CompositionError`, `ConfigError` — the CLI maps them
to exit codes 1–5 with stage-specific suggestions.

### Core invariants (accuracy/determinism guarantees — preserve in all new code)

- Rendering is **progress-driven**, never real-time: `renderFrame(t)` must be a pure
  function of `t` — no `Date.now()`, no unseeded randomness, no
  `requestAnimationFrame` timing. Same inputs → identical frames (verified by
  `tests/golden/test_determinism.py`, which re-renders and compares SHA-256).
- Templates are fully self-contained HTML (inline CSS/JS/SVG, fixed 1280×720 stage by
  convention). The registry rejects any template whose `index.html` references
  external `http(s)://` URLs in `src=`/`href=`.
- For the six fixed templates, the LLM fills template data; it never writes rendering
  code.
- The `animation` kind is the controlled exception: the model supplies `markup`,
  optional `css`, and a `js` body compiled into `draw(t)` by the template's host page
  (plus an optional `caption`). The host injects an `fx` motion library into `draw(t)`'s
  scope (`fx.pop`/`appear`/`vanish`/`glide`/`draw`/`type`/`count`/`pulse`/`camera` plus
  the `seg`/`lerp`/`ease` math helpers) so scenes are sequenced from motion primitives;
  the full contract is documented in `prompts/script_system.md`.
  `validate_animation_code()` rejects anything that
  breaks determinism or sandboxing before narration starts: `Date.now`/`new Date`/
  `performance.now`, `Math.random`/`crypto.getRandomValues`, `requestAnimationFrame`/
  `setTimeout`/`setInterval`, `fetch`/`XMLHttpRequest`/`WebSocket`/`importScripts`,
  external `src=`/`href=` URLs, and CSS `@keyframes`/`@import`/`transition:`/
  `animation:`. These code fields bypass tag-stripping in the sanitizer
  (`ANIMATION_CODE_FIELDS`); all other animation data is sanitized normally.

## Extensibility: entry points

Both templates and providers are discoverable via Python entry points, so third-party
pip-installable packages can extend the tool (see CONTRIBUTING.md for full guides):

- Group `explainer.templates`: each entry point resolves to a `get_path()` returning a
  template directory (`template.json` + `index.html`). Discovery priority (later wins
  on kind conflicts): bundled `explainer/templates/*` → user `~/.explainer/templates/*`
  → entry points.
- Group `explainer.providers`: entry points reference provider classes directly, named
  with `llm_`/`tts_` prefixes. Providers are duck-typed protocols:
  `LLMProvider.generate_script(ScriptRequest) -> Script` and
  `TTSProvider.synthesize(text, voice, out_path) -> float` (seconds) plus
  `list_voices(language)`. Defaults need no API keys: heuristic LLM and edge-tts.

## Configuration

`ExplainerConfig.resolve()` merges (highest precedence first): CLI args →
`EXPLAINER_*` env vars (`EXPLAINER_LLM`, `EXPLAINER_TTS`, `EXPLAINER_VOICE`,
`EXPLAINER_FPS`, `EXPLAINER_RESOLUTION`, `EXPLAINER_KEEP_ARTIFACTS`) →
`~/.explainer/config.toml` → defaults (`llm=None` i.e. heuristic, `tts="edge"`,
`fps=24`, `resolution="720p"`). The package does **not** auto-load `.env` — export it
first (`set -a && source .env && set +a`).

API-key checks are prefix-based and run at startup: `openai/`/`gpt/` →
`OPENAI_API_KEY`, `anthropic/`/`claude/` → `ANTHROPIC_API_KEY`, `gemini/`/`google/` →
`GOOGLE_API_KEY` or `GEMINI_API_KEY`, `moonshot/`/`kimi/` → `MOONSHOT_API_KEY`,
`deepseek/` → `DEEPSEEK_API_KEY`; TTS: `elevenlabs` → `ELEVENLABS_API_KEY`, `azure` →
`AZURE_SPEECH_KEY`, `openai` → `OPENAI_API_KEY`. A missing key raises `ConfigError`
naming the exact env var to set.

## Testing strategy

- pytest with markers declared in `pyproject.toml`: `unit`, `golden`, `e2e`, applied
  automatically by directory in `tests/conftest.py`.
- `tests/conftest.py` fixtures: `mock_tts` (silent-MP3 `MockTTSProvider`),
  `golden_script_data` / `golden_script_path`, `work_dir` (tmp dir).
- `tests/helpers.py`: silent-MP3 generator (ffmpeg or hand-built frames) and skip
  helpers `requires_chromium()` / `requires_ffmpeg()` / `requires_ffprobe()` that
  probe the environment — browser/ffmpeg-dependent tests skip cleanly when deps are
  missing.
- Golden tests render the bundled title template at t = 0 / 0.5 / 1 and assert the
  PNGs exist, are valid, and differ across t (no committed pixel baselines — they vary
  by OS/Chromium). The determinism test renders at t = 0 / 0.25 / 0.5 / 0.75 / 1
  twice and compares SHA-256 hashes. Follow this pattern when adding templates.
- The e2e test runs the pipeline with heuristic LLM and mocked narration/rendering
  stages against the real FFmpeg composer, validating the output MP4 with ffprobe.
- CI (`.github/workflows/ci.yml`): ruff + mypy on 3.11; unit tests on 3.10–3.12;
  golden and e2e jobs install ffmpeg + Chromium natively on the runner.

## Code style

- Format with `ruff format`, lint with `ruff check`. The rule set is pinned explicitly
  in `[tool.ruff.lint]` (E, F, W, I, UP, B, SIM, BLE, PLW; E501 delegated to the
  formatter; B008 waived for `explainer/cli.py` because typer uses call defaults).
- Type check with `mypy explainer/` — `[tool.mypy]` sets `strict = true`, so the bare
  command and `--strict` agree. It must stay clean. Untyped third-party libs
  (litellm, edge_tts, elevenlabs, azure) are covered by `ignore_missing_imports`.
- Google-style docstrings on public functions; type hints throughout
  (`from __future__ import annotations` at the top of every module).
- Documentation language: English. Script/narration content may be any language.
- Module layout convention: section banners (`# ---...---`), `__all__` exports,
  lazy imports inside functions for heavy optional dependencies.

## Security considerations

- Rendered HTML runs sandboxed: the renderer aborts every non-`file://` request, and
  templates must bundle everything inline (enforced at discovery by the registry).
- LLM-generated scene data is untrusted: `core/sanitize.py` recursively strips HTML
  tags, `on*=` event handlers, `javascript:` URIs, and script-bearing `data:` URIs
  before DOM injection (safe `data:image/...` URIs are preserved). Scene titles are
  sanitized too.
- Model-authored animation code is a deliberate, validated exception: it is checked
  for non-deterministic/network constructs at scripting time
  (`validate_animation_code()`), never tag-stripped, and still executes inside the
  network-blocked Chromium sandbox.
- API keys are read from env vars or `~/.explainer/config.toml`; never hardcode them.
- Third-party entry points are untrusted: a broken plugin logs a warning and never
  takes down template discovery.

## Deployment and release

- `.github/workflows/publish.yml` builds the sdist/wheel and publishes to PyPI via
  trusted publishing on `v*` tags.
- Docs are a MkDocs Material site (`docs/mkdocs.yml`) targeting GitHub Pages.
