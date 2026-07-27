# Contributing to Explainer Studio

Thank you for your interest in contributing to Explainer Studio! This guide
covers development setup, template authoring, and provider development using
the Python entry point system.

## Development Setup

### Linux / macOS

```bash
git clone https://github.com/pramodthe/explainer-studio.git
cd explainer-studio
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

Ensure FFmpeg is installed:

```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt install ffmpeg
```

### Windows (via WSL)

Explainer Studio supports Windows through the Windows Subsystem for Linux (WSL).
Native Windows is not supported due to Chromium sandboxing limitations.

1. **Install WSL 2** (if not already set up):

   ```powershell
   wsl --install -d Ubuntu-22.04
   ```

2. **Inside WSL**, install system dependencies:

   ```bash
   sudo apt update
   sudo apt install -y python3.11 python3.11-venv ffmpeg
   ```

3. **Clone and set up the project**:

   ```bash
   git clone https://github.com/pramodthe/explainer-studio.git
   cd explainer-studio
   python3.11 -m venv .venv
   source .venv/bin/activate
   pip install -e ".[dev]"
   playwright install chromium --with-deps
   ```

   The `--with-deps` flag installs Chromium's system library dependencies
   automatically on Ubuntu/Debian.

4. **Access Windows files** from WSL via `/mnt/c/Users/...`. Output videos
   can be written directly to a Windows path:

   ```bash
   explainer generate "gravity" -o /mnt/c/Users/YourName/Desktop/gravity.mp4
   ```

### Verify your environment

```bash
explainer doctor
```

This checks for FFmpeg, Chromium, and configured providers.

### Running Tests

```bash
# All tests
pytest

# By marker
pytest -m unit          # fast unit tests
pytest -m golden        # golden/snapshot tests (require Chromium)
pytest -m e2e           # end-to-end tests (require Chromium + FFmpeg)

# Lint and type check
ruff check .
ruff format --check .
mypy --strict explainer/
```

## Entry Point System

Explainer Studio uses [Python entry points](https://packaging.python.org/en/latest/specifications/entry-points/)
to discover third-party templates and providers at runtime. This allows you to
ship your own templates or providers as separate pip-installable packages.

Two entry point groups are used:

| Group | Purpose |
|---|---|
| `explainer.templates` | Scene templates (HTML/JS visual layouts) |
| `explainer.providers` | LLM and TTS provider adapters |

---

## Creating a Third-Party Template

### Directory Structure

A template is a directory containing at minimum:

```
my_template/
├── __init__.py       # Entry point module with get_path()
├── template.json     # Metadata: kind, name, version, data schema
├── index.html        # Self-contained renderer (HTML/CSS/JS/SVG)
└── preview.png       # Gallery thumbnail (optional but recommended)
```

### template.json

```json
{
  "kind": "concept",
  "name": "My Custom Concept Template",
  "version": "1.0.0",
  "schema": {
    "type": "object",
    "properties": {
      "bullets": {
        "type": "array",
        "items": { "type": "string" }
      }
    },
    "required": ["bullets"]
  },
  "default_style": {
    "bg": "#0d1b2a",
    "accent": "#4fc3f7",
    "font": "sans-serif"
  }
}
```

Fields:
- **kind** — One of: `title`, `concept`, `steps`, `compare`, `chart`, `takeaway`
- **name** — Human-readable display name
- **version** — Semver string
- **schema** — JSON Schema describing the `data` object passed to `setSceneData`
- **default_style** — Default style object passed as the second argument to `setSceneData`

### index.html Contract

Your `index.html` must expose two global functions:

```js
// Called once before frame capture — populate DOM with scene data.
window.setSceneData = function(data, style) {
    // data: matches template.json "schema"
    // style: merged default_style + any overrides
};

// Called per frame — render visual state at progress t ∈ [0, 1].
// MUST be a pure function of t (deterministic, no Date.now(), no Math.random()).
window.renderFrame = function(t) {
    // t=0: start of scene, t=1: end of scene
    // Animate elements based on t
};
```

Rules for `index.html`:
- **Self-contained**: all CSS, JS, SVG, and assets must be inline. No external
  network requests (fetch, XHR, WebSocket, external `src`/`href`).
- **Deterministic**: same `data` + same `t` → identical pixels. No `Date.now()`,
  no unseeded `Math.random()`, no `requestAnimationFrame`-based timing.
- **Fixed viewport**: design for 1280×720 (720p). The renderer will also
  support 1920×1080 (1080p) and 720×1280 (vertical).

### Entry Point Module (`__init__.py`)

```python
from pathlib import Path


def get_path() -> Path:
    """Return the path to this template's directory."""
    return Path(__file__).parent
```

The entry point must reference this function. When the registry loads the entry
point, it calls `get_path()` and expects a `Path` to the directory containing
`template.json` and `index.html`.

### Registering Your Template (pyproject.toml)

In your package's `pyproject.toml`:

```toml
[project.entry-points."explainer.templates"]
my_concept = "my_package.templates.concept:get_path"
```

The key (`my_concept`) is the entry point name (used in logs). The value points
to the `get_path` function in your module.

### Example: Full Third-Party Template Package

```
my-explainer-template/
├── pyproject.toml
├── src/
│   └── my_templates/
│       ├── __init__.py
│       └── fancy_title/
│           ├── __init__.py        # contains get_path()
│           ├── template.json
│           ├── index.html
│           └── preview.png
```

`pyproject.toml`:
```toml
[project]
name = "my-explainer-template"
version = "0.1.0"
dependencies = []

[project.entry-points."explainer.templates"]
fancy_title = "my_templates.fancy_title:get_path"
```

After `pip install my-explainer-template`, the template is automatically
discovered by `explainer templates list`.

---

## Creating a Third-Party Provider

Providers are adapters for LLM (script generation) or TTS (speech synthesis)
services. They implement a protocol interface.

### LLM Provider Interface

```python
from explainer.providers.llm_base import LLMProvider, ScriptRequest
from explainer.core.schema import Script


class MyLLMProvider:
    """Must satisfy the LLMProvider protocol."""

    def generate_script(self, request: ScriptRequest) -> Script:
        """Generate a validated Script from the request.

        Args:
            request: Contains topic, language, audience, target_duration,
                     and available_templates.

        Returns:
            A validated Script pydantic model instance.

        Raises:
            ScriptValidationError: If the output fails validation after retry.
        """
        # Your implementation here
        ...
```

The `ScriptRequest` model includes:
- `topic: str` — The educational topic
- `language: str` — BCP-47 language tag (e.g., "en", "zh-CN")
- `audience: str` — Target audience ("kid", "student", "adult")
- `target_duration: int` — Video duration in seconds
- `available_templates: list[TemplateInfo]` — Registered template metadata

### TTS Provider Interface

```python
from pathlib import Path
from explainer.providers.tts_base import TTSProvider, Voice


class MyTTSProvider:
    """Must satisfy the TTSProvider protocol."""

    def synthesize(self, text: str, voice: str, out_path: Path) -> float:
        """Convert text to speech, write MP3 to out_path.

        Args:
            text: Narration text to synthesize.
            voice: Provider-specific voice ID.
            out_path: Destination MP3 file path.

        Returns:
            Audio duration in seconds (centisecond precision).

        Raises:
            NarrationError: If synthesis fails after retry.
        """
        # Your implementation here
        ...

    def list_voices(self, language: str) -> list[Voice]:
        """List available voices filtered by language prefix.

        Args:
            language: Language prefix (e.g., "en", "zh-CN").

        Returns:
            List of Voice objects matching the filter.
        """
        # Your implementation here
        ...
```

### Registering Your Provider (pyproject.toml)

```toml
[project.entry-points."explainer.providers"]
tts_mycustom = "my_package.providers.tts_custom:MyCustomTTSProvider"
llm_mycustom = "my_package.providers.llm_custom:MyCustomLLMProvider"
```

The entry point value must reference the provider **class** directly.

Naming convention:
- LLM providers: prefix with `llm_` (e.g., `llm_mycustom`)
- TTS providers: prefix with `tts_` (e.g., `tts_mycustom`)

### Example: Full Third-Party Provider Package

```
my-explainer-tts/
├── pyproject.toml
├── src/
│   └── my_tts/
│       ├── __init__.py
│       └── provider.py      # Contains MyTTSProvider class
```

`pyproject.toml`:
```toml
[project]
name = "my-explainer-tts"
version = "0.1.0"
dependencies = ["explainer-studio"]

[project.entry-points."explainer.providers"]
tts_mytts = "my_tts.provider:MyTTSProvider"
```

After `pip install my-explainer-tts`, the provider is available:

```bash
explainer generate "gravity" --tts mytts
```

---

## Testing Your Extension

### Templates

1. Install your package in editable mode: `pip install -e .`
2. Verify discovery: `explainer templates list` should show your template
3. Preview: `explainer templates preview <kind>` renders at t=0, 0.5, 1.0
4. Generate a video using your template kind to confirm it works end-to-end

### Providers

1. Install in editable mode: `pip install -e .`
2. Test via CLI: `explainer generate "test topic" --tts mytts` or `--llm mymodel`
3. Run the project test suite: `pytest tests/`

---

## Code Style

- Format with `ruff format`
- Lint with `ruff check` — the rule set is pinned in `[tool.ruff.lint]`
- Type check with `mypy explainer/` — `[tool.mypy]` sets `strict = true`
- All public functions need docstrings (Google style)
- Documentation language: English

## Submitting Changes

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure `ruff check` and `mypy` pass
5. Open a pull request with a clear description

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE) that covers this project.
