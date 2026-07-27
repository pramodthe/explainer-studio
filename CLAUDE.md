# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Explainer Studio (`explainer-studio` on PyPI) generates narrated, animated educational explainer videos (MP4) from a topic string. Python package with a typer CLI (`explainer`) and a library API (`from explainer import Pipeline, Script`).

Licensed MIT. `AGENTS.md` is the detailed companion to this file (layout, pipeline internals, invariants) and is accurate — it only *mentions* the removed `explainer_studio/`/`app/` prototype to tell you to ignore it. `llms.txt` is the short machine-readable summary, and `.claude/skills/explainer-studio/SKILL.md` is the task playbook. Formal specs live in `.kiro/specs/explainer-studio/` (requirements.md, design.md, tasks.md).

## Commands

```bash
# Setup (a .venv already exists in this repo)
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium        # rendering engine
explainer doctor                   # verify ffmpeg/ffprobe, Chromium, providers

# Tests (markers declared in pyproject.toml, applied by directory in tests/conftest.py)
pytest -m unit                     # fast, no external deps
pytest -m golden                   # snapshot tests — require Chromium
pytest -m e2e                      # require Chromium + FFmpeg
pytest tests/unit/test_schema.py::test_name   # single test

# Lint / type check (config pinned in pyproject.toml; mypy strict = true)
ruff check .
ruff format --check .
mypy explainer/
```

CI (`.github/workflows/ci.yml`): ruff + mypy, unit tests on Python 3.10–3.12, and golden/e2e jobs that install ffmpeg + Chromium natively on the runner.

## Architecture

Four-stage deterministic pipeline, orchestrated by `explainer/core/pipeline.py` (`Pipeline.generate()`; `Pipeline.render()` skips stage 1):

1. **Scripting** — an LLM provider produces a `Script` (pydantic model in `core/schema.py`): 3–6 scenes, first must be `title`, last must be `takeaway`. Each `Scene` has a `kind` (one of `title|concept|steps|compare|chart|takeaway|animation`), `narration`, and template-specific `data`. `Script.validate_with_templates()` checks each scene's `data` against the template's JSON Schema.
2. **Narration (TTS)** — one MP3 per scene. **Audio-first timing is a hard invariant**: scene duration = audio duration + 0.4s tail pad (`_TAIL_PAD_SECONDS`); narration length defines scene length, never the reverse.
3. **Rendering** (`core/renderer.py`) — each scene renders in its own headless Chromium via Playwright (parallel per scene through `ProcessPoolExecutor`, ≤4 workers). All non-`file://` network requests are blocked. The page's `window.setSceneData(data, style)` is called once, then `window.renderFrame(t)` per frame stepping t from 0→1, screenshotting `f{NNNN}.png`. Scene data passes through `core/sanitize.py` before injection (LLM output is untrusted).
4. **Composition** (`core/composer.py`) — FFmpeg encodes per-scene segments (frames + audio) and concatenates them into the final MP4.

Work happens in a temp dir (`explainer-*`), cleaned up unless `keep_artifacts=True`. Progress is reported via an `on_progress` callback receiving `ProgressEvent(stage, pct, message)`.

### Core invariants (accuracy/determinism guarantees — preserve in all new code)

- Rendering is **progress-driven**, never real-time: `renderFrame(t)` must be a pure function of t (no `Date.now()`, no unseeded randomness, no `requestAnimationFrame` timing). Same inputs → pixel-identical video.
- For the six fixed templates the LLM fills schema-validated `data` only. The seventh
  kind, `animation`, is a host that runs **model-authored** markup/css/js through
  `draw(t)`; `core/sanitize.py::validate_animation_code()` rejects anything
  non-deterministic (Date/Math.random/timers) or networked before it renders.
- Templates are fully self-contained HTML (inline CSS/JS/SVG, no external requests). The registry rejects any template whose `index.html` contains external `src=`/`href=` URLs.

### Extensibility (entry points)

- `core/registry.py` discovers templates in priority order (later wins): bundled `explainer/templates/*` → user `~/.explainer/templates/*` → entry points in group `explainer.templates` (each resolves to a `get_path()` returning the template dir containing `template.json` + `index.html`).
- Providers are duck-typed protocols in `explainer/providers/` (`llm_base.LLMProvider.generate_script`, `tts_base.TTSProvider.synthesize/list_voices`), registered in entry point group `explainer.providers` with `llm_`/`tts_` name prefixes. Defaults require no API keys: heuristic LLM (`llm_heuristic.py`) and edge-tts (`tts_edge.py`); other providers (litellm, ElevenLabs, Azure, OpenAI TTS) need API keys validated by `config.py`.
- Config resolution (`config.py`): CLI args > `EXPLAINER_*` env vars > `~/.explainer/config.toml` > defaults.

### Tests

`tests/conftest.py` provides `mock_tts` (silent-MP3 `MockTTSProvider` from `tests/helpers.py`), `golden_script_data`/`golden_script_path` (fixture at `tests/fixtures/golden_script.json`), and `work_dir`. Golden tests render templates at t = 0 / 0.5 / 1 and snapshot-diff; determinism tests re-render and compare pixels — follow this pattern for new templates.

## Style

- `ruff format` / `ruff check`; `mypy --strict`; Google-style docstrings on public functions; documentation in English.
