# Python API Reference

Explainer Studio exposes its core functionality as a Python library.

```python
from explainer import Pipeline, Script, Scene, SceneKind
```

---

## Pipeline

The main entry point for video generation.

### `Pipeline.__init__`

```python
Pipeline(
    llm: str | None = None,
    tts: str = "edge",
    voice: str | None = None,
    on_progress: Callable[[ProgressEvent], None] | None = None,
)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `llm` | `str \| None` | `None` | LLM model string (e.g., `"openai/gpt-5.6"`). `None` uses the heuristic generator. |
| `tts` | `str` | `"edge"` | TTS provider name |
| `voice` | `str \| None` | `None` | Voice ID (provider-specific). `None` uses the provider's default. |
| `on_progress` | callback | `None` | Called with `ProgressEvent` on stage transitions and progress updates |

### `Pipeline.generate`

Run the full 4-stage pipeline: script → narration → rendering → composition.

```python
Pipeline.generate(
    topic: str,
    *,
    language: str = "en",
    audience: str = "student",
    target_duration: int = 60,
    fps: int = 15,
    resolution: str = "720p",
    music: str | None = None,
    out: str | None = None,
    keep_artifacts: bool = False,
) -> GenerateResult
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `topic` | `str` | — | Educational topic to explain |
| `language` | `str` | `"en"` | BCP-47 language code |
| `audience` | `str` | `"student"` | Target audience: `"kid"`, `"student"`, `"adult"` |
| `target_duration` | `int` | `60` | Target video length in seconds (30, 60, or 90) |
| `fps` | `int` | `15` | Frame rate (15, 24, or 30) |
| `resolution` | `str` | `"720p"` | Output resolution: `"720p"`, `"1080p"`, `"vertical"` |
| `music` | `str \| None` | `None` | Path to background music file |
| `out` | `str \| None` | `None` | Output MP4 path. Defaults to `./<topic-slug>.mp4` |
| `keep_artifacts` | `bool` | `False` | Retain intermediate files after completion |

**Returns:** `GenerateResult`

**Raises:**

- `ScriptValidationError` — script generation or validation failed
- `NarrationError` — TTS synthesis failed for a scene
- `RenderError` — frame rendering failed
- `CompositionError` — FFmpeg encoding failed
- `ConfigError` — missing API key or invalid configuration

### `Pipeline.render`

Skip script generation and run narration → rendering → composition from an existing Script.

```python
Pipeline.render(
    script: Script,
    *,
    out: str | None = None,
    fps: int = 15,
    resolution: str = "720p",
    music: str | None = None,
    keep_artifacts: bool = False,
    on_progress: Callable[[ProgressEvent], None] | None = None,
) -> GenerateResult
```

**Parameters:** Same as `generate` minus `topic`/`language`/`audience`/`target_duration`, plus a `Script` object.

---

## GenerateResult

Returned by `Pipeline.generate()` and `Pipeline.render()`.

```python
@dataclass
class GenerateResult:
    mp4_path: Path  # Path to the output MP4 file
    script: Script  # The Script used for generation
    work_dir: Path  # Work directory (empty if keep_artifacts=False)
```

---

## ProgressEvent

Emitted to the `on_progress` callback during pipeline execution.

```python
@dataclass
class ProgressEvent:
    stage: str  # "scripting" | "narrating" | "rendering" | "composing" | "done"
    pct: float  # 0.0 – 100.0
    message: str  # e.g., "rendering scene 3/4"
```

---

## Script

A pydantic model representing the video script.

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `topic` | `str` | — | The educational topic |
| `language` | `str` | `"en"` | Language code |
| `audience` | `Literal["kid", "student", "adult"]` | `"student"` | Target audience |
| `scenes` | `list[Scene]` | — | 3–6 scenes; first must be `title`, last must be `takeaway` |

### Validation Rules

- Must contain 3–6 scenes
- First scene must have `kind = "title"`
- Last scene must have `kind = "takeaway"`

### `Script.from_file`

Load a script from a JSON file.

```python
script = Script.from_file("my_script.json")
```

### `Script.to_file`

Save a script to a JSON file.

```python
script.to_file("output_script.json")
```

---

## Scene

A single scene within a Script.

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | `int` | — | Sequential scene identifier |
| `kind` | `SceneKind` | — | Template kind to render |
| `title` | `str` | — | Scene heading |
| `narration` | `str` | — | Narration text (≤ ~400 characters) |
| `data` | `dict` | `{}` | Template-specific data (validated against template JSON Schema) |
| `duration_hint` | `float \| None` | `None` | Optional hint; actual duration comes from audio length |

---

## SceneKind

Enum of available template types.

```python
class SceneKind(str, Enum):
    TITLE = "title"
    CONCEPT = "concept"
    STEPS = "steps"
    COMPARE = "compare"
    CHART = "chart"
    TAKEAWAY = "takeaway"
```

---

## Exceptions

All exceptions inherit from `ExplainerError` and include `stage` and `message` attributes.

| Exception | Stage | Extra Fields |
|-----------|-------|--------------|
| `ScriptValidationError` | `"scripting"` | — |
| `NarrationError` | `"narrating"` | `scene_id: int` |
| `RenderError` | `"rendering"` | `scene_id: int`, `frame_index: int \| None` |
| `CompositionError` | `"composing"` | `ffmpeg_stderr: str` |
| `ConfigError` | `"config"` | — |

### Example: Error handling

```python
from explainer import Pipeline
from explainer.core.errors import NarrationError, RenderError

pipeline = Pipeline()
try:
    result = pipeline.generate("photosynthesis")
except NarrationError as e:
    print(f"TTS failed on scene {e.scene_id}: {e.message}")
except RenderError as e:
    print(f"Rendering failed on scene {e.scene_id}, frame {e.frame_index}")
```

---

## Complete Example

```python
from explainer import Pipeline, Script, SceneKind, Scene

# Option 1: Generate from topic
pipeline = Pipeline(
    llm="openai/gpt-5.6",
    tts="edge",
    voice="en-US-GuyNeural",
    on_progress=lambda e: print(f"[{e.stage}] {e.pct:.0f}%"),
)
result = pipeline.generate(
    "photosynthesis",
    language="en",
    audience="student",
    target_duration=60,
    fps=24,
    resolution="1080p",
    out="photosynthesis.mp4",
)

# Option 2: Build a script programmatically
script = Script(
    topic="gravity",
    language="en",
    audience="student",
    scenes=[
        Scene(id=1, kind=SceneKind.TITLE, title="Gravity", narration="...", data={}),
        Scene(
            id=2,
            kind=SceneKind.CONCEPT,
            title="What is Gravity?",
            narration="...",
            data={"bullets": ["..."]},
        ),
        Scene(
            id=3,
            kind=SceneKind.TAKEAWAY,
            title="Summary",
            narration="...",
            data={"points": ["..."]},
        ),
    ],
)
script.to_file("gravity_script.json")
result = pipeline.render(script, out="gravity.mp4")

# Option 3: Load and modify a script
script = Script.from_file("gravity_script.json")
script.scenes[1].narration = "Updated narration text."
result = pipeline.render(script)
```
