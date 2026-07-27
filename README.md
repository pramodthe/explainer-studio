<div align="center">

# 🎬 Explainer Studio

**Turn a topic string into a narrated, animated explainer video.**

One command in, one MP4 out. An LLM writes the script, a TTS voice narrates it, headless
Chromium animates it, and FFmpeg cuts it together — deterministically, with no API keys
required for your first run.

[![CI](https://github.com/pramodthe/explainer-studio/actions/workflows/ci.yml/badge.svg)](https://github.com/pramodthe/explainer-studio/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/badge/PyPI-explainer--studio-3775a9?logo=pypi&logoColor=white)](https://pypi.org/project/explainer-studio/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white)](pyproject.toml)
[![Typed: strict](https://img.shields.io/badge/mypy-strict-2a6db2)](pyproject.toml)

[Quickstart](#-quickstart) · [How it works](#-how-it-works) · [CLI](#-cli-reference) ·
[Python API](#-python-api) · [Templates](#-templates) · [Providers](#-providers) ·
[Determinism](#-determinism-and-safety) · [Extending](#-extending-it)

```
  "photosynthesis"
        │
        ▼
┌─────────────────┐  Script     ┌─────────────────┐  MP3/scene   ┌─────────────────┐
│  1. Scripting   │ ──────────▶ │  2. Narration   │ ───────────▶ │  3. Rendering   │
│  LLM picks +    │  3–6 scenes │  TTS per scene  │  audio-first │  Chromium       │
│  fills templates│             │                 │  timing      │  frames @ t→1   │
└─────────────────┘             └─────────────────┘              └────────┬────────┘
                                                                          │ PNGs
                                                                 ┌────────▼────────┐
                                                                 │ 4. Composition  │
                                                                 │ FFmpeg → MP4    │
                                                                 └─────────────────┘
```

</div>

---

## Why Explainer Studio?

Most "AI video" tools either hand the model a rendering engine and hope for the best, or
lock you into a hosted service. Both make the output unpredictable: run the same prompt
twice, get two different videos.

Explainer Studio splits the job at a hard boundary — not "can the model draw?" but **"is
every frame a pure function of progress `t ∈ [0, 1]`?"** Six templates are hand-authored,
self-contained HTML the model merely fills with schema-validated data. A seventh,
`animation`, lets the model author the markup and `draw(t)` itself — and that code is
rejected before rendering if it touches wall-clock time, randomness, timers or the
network. Either way: same script in, pixel-identical MP4 out, on your machine or in CI.

The other half is timing. Narration length defines scene length, never the reverse: each
scene lasts exactly as long as its audio plus a 0.4 s tail pad, so the voice is never cut
off mid-sentence and animations never wait on an empty screen.

|                          | Explainer Studio | Prompt-to-video services |
| ------------------------ | ---------------- | ------------------------ |
| Same input → same output | ✅ pixel-identical | ❌ re-rolled every run  |
| Runs offline / no keys   | ✅ heuristic LLM + edge-tts | ❌ hosted API   |
| Rendering code authored by | you (HTML templates) | the model            |
| Inspectable intermediates | ✅ script JSON, frames, audio | ❌ opaque      |
| Photoreal b-roll         | ❌ (vector/HTML scenes) | ✅                  |

Good for: course material, documentation companions, release notes as video, internal
training — anything where you want the *same* explainer back when the content changes.

## 📦 What's in the box

| Piece | What it is |
| ----- | ---------- |
| [`explainer` CLI](#-cli-reference) | `generate`, `doctor`, `init`, `voices`, `templates` |
| [`explainer` library](#-python-api) | `Pipeline.generate()` / `.render()`, `Script`, `Scene`, `ProgressEvent` |
| [7 scene templates](#-templates) | title, concept, steps, compare, chart, takeaway, animation — self-contained HTML |
| [Provider adapters](#-providers) | LLM via litellm or heuristic; TTS via edge-tts (free, 300+ voices) |
| [Entry-point plugins](#-extending-it) | ship your own templates and providers as pip packages |

## ⚡ Try it in one command

No API keys, no account, no config:

```bash
pip install explainer-studio && playwright install chromium
explainer generate "photosynthesis"
```

The built-in heuristic scripter and free edge-tts voice produce a ~60 s, 720p MP4 in the
current directory. Swap in a real model whenever you want — everything downstream is
unchanged:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
explainer generate "photosynthesis" --llm anthropic/claude-sonnet-5
```

## 🚀 Quickstart

### 1. Install

```bash
pip install explainer-studio
playwright install chromium        # the rendering engine
```

You also need **FFmpeg** (with `ffprobe`) on `PATH` — `brew install ffmpeg` on macOS,
`sudo apt install ffmpeg` on Debian/Ubuntu. Then confirm everything resolves:

```bash
explainer doctor
```

```
Explainer Studio — System Check

  ✓ ffmpeg: ffmpeg version 7.1 …
  ✓ ffprobe: found
  ✓ Chromium (Playwright): installed
All checks passed!
```

Narration needs no setup: edge-tts is free and keyless. Pick a voice with
`explainer voices --lang en`, then pass e.g. `--voice en-US-AndrewMultilingualNeural`.
For OpenAI voices instead: `pip install "explainer-studio[openai]"` and
`--tts openai --voice marin`.

### 2. Generate

```bash
explainer generate "how a transformer works" \
  --audience adult \
  --duration 90 \
  --res 1080p \
  --llm openai/gpt-5.6 \
  -o transformer.mp4
```

### 3. Or drive it from Python

```python
from explainer import Pipeline

pipeline = Pipeline(llm="openai/gpt-5.6", tts="edge")
result = pipeline.generate("photosynthesis", audience="student", target_duration=60)

print(result.mp4_path)  # Path to the finished MP4
print(len(result.script.scenes))  # 3–6 scenes
```

### 4. Edit the script, re-render only

`generate` and `render` are separate stages on purpose. Save a script, tweak the wording,
and re-render without paying for the LLM again:

```python
result.script.to_file("photosynthesis.json")
```

```bash
explainer generate "photosynthesis" --script photosynthesis.json -o v2.mp4
```

## 🔍 How it works

Four deterministic stages, orchestrated by [`Pipeline.generate()`](explainer/core/pipeline.py).

**1. Scripting.** An LLM provider receives the topic, audience, target duration, and the
JSON Schema of every discovered template, and returns a `Script`: 3–6 scenes, the first a
`title`, the last a `takeaway`. Each scene names a template `kind` and supplies `data`
matching that template's schema, plus the `narration` text. The result is validated by
pydantic *and* against each template's schema before anything renders.

**2. Narration.** One MP3 per scene. Scene duration is then fixed at
`audio_duration + 0.4 s` — a hard invariant. Narration length defines scene length, never
the reverse.

**3. Rendering.** Each scene gets its own headless Chromium (in parallel, up to
`min(4, cpu_count)` processes). The page loads the template over `file://` with **all
non-`file://` requests blocked**, receives `window.setSceneData(data, style)` once, then
`window.renderFrame(t)` per frame with `t` stepping `0 → 1` across the scene's duration.
Every frame is screenshotted to `f{NNNN}.png`.

**4. Composition.** FFmpeg encodes each scene's frames against its audio, then concatenates
the segments into the final MP4.

Work happens in a temp directory (`explainer-*`), removed afterwards unless you pass
`--keep-artifacts`. Progress is reported throughout via `ProgressEvent(stage, pct, message)`.

## 🖥 CLI reference

| Command | What it does |
| ------- | ------------ |
| `explainer generate <topic>` | Run the full pipeline and write an MP4 |
| `explainer doctor` | Verify FFmpeg, ffprobe, and Chromium are usable |
| `explainer init` | Interactively write `~/.explainer/config.toml` |
| `explainer templates list` | Show discovered templates and versions |
| `explainer templates preview <kind>` | Render one template at t = 0, 0.5, 1.0 |
| `explainer voices [--lang en]` | List voices from the configured TTS provider |

### `generate` options

| Flag | Default | Description |
| ---- | ------- | ----------- |
| `--lang` | `en` | Language code (`en`, `zh`, `es`, …) |
| `--audience` | `student` | `kid`, `student`, or `adult` |
| `--duration` | `60` | Target duration in seconds (30 / 60 / 90) |
| `--fps` | `15` | Frames per second (15 / 24 / 30) |
| `--res` | `720p` | `720p`, `1080p`, `vertical`, or explicit `WxH` |
| `--llm` | heuristic | litellm model string, e.g. `openai/gpt-5.6` |
| `--tts` | `edge` | `edge`, `elevenlabs`, `azure`, `openai` |
| `--voice` | provider default | Voice id (see `explainer voices`) |
| `--music` | — | Background music track to mix under narration |
| `--script` | — | Pre-built script JSON — skips the LLM entirely |
| `--keep-artifacts` | off | Keep the work dir (frames, audio, segments) |
| `-o`, `--out` | auto | Output MP4 path |

Exit codes are stage-specific, so CI can tell *what* broke: `1` script validation,
`2` narration, `3` rendering, `4` composition, `5` config.

## 🐍 Python API

### `Pipeline(llm=None, tts="edge", voice=None, on_progress=None)`

```python
from explainer import Pipeline, Script


def on_progress(event):
    print(f"[{event.stage:>10}] {event.pct:5.1f}%  {event.message}")


pipeline = Pipeline(llm="anthropic/claude-sonnet-5", on_progress=on_progress)
```

| Method | Purpose |
| ------ | ------- |
| `.generate(topic, *, language, audience, target_duration, fps, resolution, music, out, keep_artifacts)` | Full pipeline: script → narrate → render → compose |
| `.render(script, *, out, fps, resolution, music, keep_artifacts, on_progress)` | Skip stage 1 and render an existing `Script` |

Both return a `GenerateResult` with `.mp4_path`, `.script`, and `.work_dir`.

### Scripts are data

`Script` is a pydantic model, so it round-trips to JSON and can be edited, diffed, and
version-controlled like any other artifact:

```python
script = Script.from_file("photosynthesis.json")
script.scenes[1].narration = "Chlorophyll absorbs red and blue light, reflecting green."
result = pipeline.render(script, resolution="1080p")
```

Validation rules enforced on every `Script`: 3–6 scenes, first scene `title`, last scene
`takeaway`, and each scene's `data` conforming to its template's JSON Schema.

Full reference: [docs/api.md](docs/api.md).

## 🎨 Templates

A scene's `kind` selects the template that draws it.

| Kind | Name | `data` fields |
| ---- | ---- | ------------- |
| `title` | Title Card | *(none — uses the scene's `title`)* |
| `concept` | Concept / Definition | `bullets`, `diagram` |
| `steps` | Step-by-Step | `steps` |
| `compare` | Comparison | `left`, `right` |
| `chart` | Chart / Visualization | `chart_type`, `labels`, `values` |
| `takeaway` | Key Takeaway | `bullets` |
| `animation` | Custom Animation | `markup`, `js`, + optional `css`, `caption` |

Each template is a directory with a `template.json` (metadata + JSON Schema + default
style) and a fully self-contained `index.html` exposing exactly two globals:

```js
window.setSceneData(data, style)   // called once, before any frame
window.renderFrame(t)              // called per frame; t ∈ [0, 1]
```

`renderFrame(t)` **must be a pure function of `t`**. No `Date.now()`, no
`requestAnimationFrame`, no unseeded `Math.random()` — that purity is what makes output
reproducible. The registry also rejects any template whose `index.html` references an
external `src=` or `href=` URL.

Authoring guide: [docs/templates.md](docs/templates.md).

### The `animation` kind

The first six templates are fixed layouts the model fills with data. `animation` is
different: it's a **host** that runs graphics the model writes itself, for ideas better
shown than listed.

```json
{
  "markup": "<svg viewBox='0 0 900 400'>…<line id='arrow' …/></svg>",
  "js": "document.getElementById('arrow').setAttribute('x2', String(lerp(200, 820, ease(seg(t, 0.3, 1)))));",
  "caption": "Tokens flow into attention"
}
```

`js` is the body of `draw(t)`, called once per frame. The host provides `seg(t, a, b)` to
give each element its own slice of the timeline, plus `ease`, `lerp`, `clamp` and the
deck's `accent` colour — so a scene unfolds in step with the narration.

Model-written code is screened before it renders. `Date`, `Math.random`, `setTimeout`,
`requestAnimationFrame`, `fetch`, external URLs and CSS `transition`/`@keyframes` are
rejected (they would break reproducibility); `<script>` tags, `on*=` handlers and
`javascript:`/`data:` URIs are stripped from `markup`. Violations fail the scripting
stage, before any narration is paid for.

## 🔌 Providers

Both provider types are duck-typed protocols — implement the method, register the entry
point, done.

**LLM** — `generate_script(request) -> Script`

| Name | Notes |
| ---- | ----- |
| heuristic | Default. Offline, deterministic, no API key. |
| litellm | Any model litellm supports — pass the vendor-prefixed string |

Current model strings (verified July 2026). Scripting is a short, structured task, so a
balanced tier is usually the right pick:

| Vendor | Flagship | Balanced | Cheapest |
| ------ | -------- | -------- | -------- |
| OpenAI | `openai/gpt-5.6` | `openai/gpt-5.6-terra` | `openai/gpt-5.6-luna` |
| Anthropic | `anthropic/claude-opus-5` | `anthropic/claude-sonnet-5` | `anthropic/claude-haiku-4-5-20251001` |
| Google | `gemini/gemini-3.1-pro-preview` | `gemini/gemini-3.6-flash` | `gemini/gemini-3.5-flash-lite` |
| DeepSeek | `deepseek/deepseek-v4-pro` | `deepseek/deepseek-v4-flash` | — |
| Moonshot | `moonshot/kimi-k3` | — | — |

**TTS** — `synthesize(text, voice, out_path) -> float` and `list_voices(language)`

| Name | Status | Key |
| ---- | ------ | --- |
| edge | **Implemented.** Free, 300+ voices. Default. | none |
| openai | **Implemented.** `gpt-4o-mini-tts`, 13 voices, style steering. | `OPENAI_API_KEY` |
| elevenlabs | Reserved — adapter not implemented yet | — |
| azure | Reserved — adapter not implemented yet | — |

Pick a **voice**, not a model. `explainer voices --lang en` lists what the configured
provider offers, then pass e.g. `--voice en-US-AndrewMultilingualNeural` (edge) or
`--voice marin` (openai). Asking for an unimplemented provider fails at startup rather
than quietly substituting a different voice.

Configuration resolves **CLI flags → `EXPLAINER_*` env vars → `~/.explainer/config.toml` →
defaults**. A missing API key is caught at startup with a message naming the exact
variable, not halfway through a render. See [.env.example](.env.example) for every
variable and [docs/providers.md](docs/providers.md) for details.

## 🔒 Determinism and safety

These are guarantees, not aspirations — the test suite checks them.

- **Reproducible.** `renderFrame(t)` is pure in `t`; rendering is progress-driven, never
  real-time. `tests/golden/test_determinism.py` renders twice and asserts every frame is
  byte-identical by SHA-256.
- **Offline rendering.** Chromium blocks every non-`file://` request, so a template cannot
  phone home and rendering works air-gapped.
- **Untrusted model output.** LLM-produced scene data passes through
  [`core/sanitize.py`](explainer/core/sanitize.py) before injection — HTML tags, `on*=`
  handlers, `javascript:` URIs, and executable `data:` URIs are stripped and logged.
- **Model-authored code is checked, not trusted.** Six templates take data only. The
  `animation` kind runs model-written `draw(t)`, screened by
  [`validate_animation_code()`](explainer/core/sanitize.py) for `Date`, `Math.random`,
  timers, `fetch` and external URLs — violations fail the script stage.
- **Snapshot-tested templates.** Golden tests render each template at t = 0 / 0.5 / 1 and
  diff against committed snapshots.

## 🧩 Extending it

Templates and providers are discovered through Python entry points, so a plugin is just a
pip-installable package:

```toml
# your-package/pyproject.toml
[project.entry-points."explainer.templates"]
timeline = "my_templates.timeline:get_path"      # returns the template directory

[project.entry-points."explainer.providers"]
tts_mycloud = "my_providers.cloud:MyTTSProvider" # llm_* / tts_* name prefix
```

Templates resolve in priority order, later winning: bundled → `~/.explainer/templates/*` →
entry points. Drop a directory into `~/.explainer/templates/` to override a bundled
template without touching the package.

## 📚 Documentation

| Page | Contents |
| ---- | -------- |
| [docs/quickstart.md](docs/quickstart.md) | Install → first video, step by step |
| [docs/cli.md](docs/cli.md) | Every command, flag, and exit code |
| [docs/api.md](docs/api.md) | `Pipeline`, `Script`, `Scene`, `GenerateResult` |
| [docs/templates.md](docs/templates.md) | Template contract and authoring guide |
| [docs/providers.md](docs/providers.md) | LLM/TTS adapters and configuration |
| [AGENTS.md](AGENTS.md) | Repo layout and rules for AI coding agents |
| [llms.txt](llms.txt) | Machine-readable project summary |

## 🤖 For AI coding agents

Start with [llms.txt](llms.txt) for a compact orientation, then [AGENTS.md](AGENTS.md) for
the repo layout, commands, and the invariants you must not break. The short version:
narration defines scene duration, `renderFrame(t)` stays pure in `t`, templates stay
self-contained, and the LLM never emits rendering code.

## 🤝 Contributing

```bash
git clone https://github.com/pramodthe/explainer-studio.git
cd explainer-studio
pip install -e ".[dev]"
playwright install chromium

pytest -m unit          # fast, no external dependencies
pytest -m golden        # snapshot + determinism (needs Chromium)
pytest -m e2e           # end-to-end (needs Chromium + FFmpeg)

ruff check . && ruff format --check . && mypy explainer/
```

New templates need a golden test and a determinism test — see
[CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.

## 📄 License

MIT — see [LICENSE](LICENSE).

---

<div align="center">
<sub>Built for people who want the same explainer back when they regenerate it.</sub>
</div>
