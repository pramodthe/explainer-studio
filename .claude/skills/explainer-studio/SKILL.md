---
name: explainer-studio
description: >-
  Generate narrated, animated explainer videos from a topic string with Explainer Studio,
  and author custom scene templates or LLM/TTS providers for it. Use when asked to turn
  notes, docs, or a topic into an educational video, to script/narrate/render an explainer
  MP4, to add a new scene template or provider, or to debug the four-stage pipeline
  (scripting → narration → rendering → composition).
---

# Working with Explainer Studio

`explainer-studio` (PyPI) turns a topic string into a narrated, animated MP4. Four
deterministic stages: an LLM fills schema-validated **templates**, TTS narrates each
scene, headless Chromium renders frames from `t = 0 → 1`, FFmpeg composes the video.

The most important rule: **every frame must be a pure function of `t`.** Six templates
take schema-validated `data` only. The seventh kind, `animation`, does let the model
author markup/css/js run as `draw(t)` — use it when an idea is better shown than listed —
but that code is rejected if it uses `Date`, `Math.random`, timers, `fetch` or external
URLs. For visuals you want repeated across many topics, author a template instead.

## Setup (do this first)

```bash
pip install explainer-studio
playwright install chromium          # the rendering engine — pip does not install it
explainer doctor                     # verifies ffmpeg, ffprobe, Chromium
```

FFmpeg **and** `ffprobe` must be on PATH. If `doctor` reports anything missing, fix that
before generating — a missing binary surfaces late, as a composition or narration error.
No API keys are needed: the defaults are the heuristic scripter and free edge-tts.

## Generating a video

```bash
explainer generate "photosynthesis" -o out.mp4
```

Common flags: `--llm openai/gpt-5.6` (any litellm model string), `--audience kid|student|adult`,
`--duration 30|60|90`, `--res 720p|1080p|vertical`, `--fps 15|24|30`, `--voice`,
`--music`, `--keep-artifacts`.

From Python:

```python
from explainer import Pipeline

pipeline = Pipeline(
    llm="anthropic/claude-sonnet-5",
    on_progress=lambda e: print(e.stage, e.pct),
)
result = pipeline.generate("photosynthesis", audience="student", target_duration=60)
result.script.to_file("photosynthesis.json")  # keep the script — it is plain data
```

### Prefer editing the script over re-prompting

The script is a pydantic model that round-trips to JSON. When wording or structure is
wrong, edit the JSON and re-render — it is faster, cheaper, and deterministic:

```bash
explainer generate "photosynthesis" --script photosynthesis.json -o v2.mp4
```

A valid `Script` has 3–6 scenes, the first `kind: title`, the last `kind: takeaway`, and
each scene's `data` matching its template's JSON Schema.

## Authoring a template

Templates live in `explainer/templates/<kind>/` (bundled), `~/.explainer/templates/<kind>/`
(user), or any package exposing an `explainer.templates` entry point. Later wins.

Each directory needs `template.json` (metadata, JSON Schema for `data`, default style) and
a self-contained `index.html` defining exactly two globals:

```js
window.setSceneData(data, style)   // called once, before any frame
window.renderFrame(t)              // called per frame; t ∈ [0, 1]
```

Hard requirements — violating any of these breaks the project's guarantees:

- **`renderFrame(t)` must be pure in `t`.** No `Date.now()`, no `performance.now()`, no
  `requestAnimationFrame`, no unseeded `Math.random()`, no CSS animations/transitions that
  advance on wall-clock. Derive every visual state from `t` alone.
- **Fully self-contained.** Inline all CSS, JS, and SVG. The registry rejects any
  `index.html` with an external `src=`/`href=` URL, and Chromium blocks non-`file://`
  requests at render time, so a remote asset fails twice over.
- **Fixed 1280×720 stage** by convention; scale to the viewport with transforms.
- **Treat `data` as untrusted.** It comes from an LLM and is sanitized upstream — render it
  as text (`textContent`), never `innerHTML`.

Then add both tests, mirroring the existing ones: a golden test rendering at
t = 0 / 0.5 / 1 with snapshot diffing, and a determinism test that re-renders and compares
frame hashes. `pytest -m golden` must pass.

## Authoring a provider

Providers are duck-typed protocols — no base class to inherit.

```python
# LLM: explainer/providers/llm_base.py
def generate_script(self, request: ScriptRequest) -> Script: ...


# TTS: explainer/providers/tts_base.py
# synthesize() writes the audio file and returns its duration in seconds.
def synthesize(self, text: str, voice: str, out_path: Path) -> float: ...
def list_voices(self, language: str) -> list[Voice]: ...
```

Register under the `explainer.providers` entry-point group with an `llm_` or `tts_` name
prefix. `synthesize` returning an accurate duration matters: **scene length is derived from
it** (audio duration + 0.4 s tail pad). Never invert that relationship by trimming or
padding narration to fit a target scene length.

## Debugging the pipeline

Exit codes name the failing stage: `1` script validation, `2` narration, `3` rendering,
`4` composition, `5` config.

| Symptom | Where to look |
| ------- | ------------- |
| Script rejected | Scene count outside 3–6, wrong first/last kind, or `data` failing the template schema |
| Narration fails | TTS provider key (`explainer doctor`), or `ffprobe` missing — duration is measured with it |
| Render fails | Template threw inside `setSceneData`/`renderFrame`; run `explainer templates preview <kind>` to isolate |
| Frames identical / blank | `renderFrame(t)` ignoring `t`, or drawing on a timer instead of from `t` |
| Video drifts from audio | Something bypassed the audio-first invariant |
| Composition fails | FFmpeg not on PATH, or a scene produced zero frames |

`--keep-artifacts` preserves the work directory (per-scene frames, MP3s, segment MP4s) —
inspect it before assuming the bug is in the pipeline rather than the template.

## Checks before you finish

```bash
pytest -m unit && pytest -m golden      # golden needs Chromium
ruff check . && ruff format --check . && mypy explainer/
```
