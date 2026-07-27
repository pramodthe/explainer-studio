# Explainer Studio

**Turn any topic into a narrated, animated educational explainer video — fully automatically.**

Explainer Studio is an open-source Python package that generates short (30–90s) explainer videos from a single topic string. It ships as both a CLI tool and a Python library with pluggable LLM and TTS providers, a template-based rendering system, and zero-config defaults.

## Overview

The pipeline has four stages:

1. **Script Generation** — An LLM (or heuristic fallback) creates a structured script with 3–6 scenes
2. **Narration** — Text-to-speech synthesizes audio for each scene
3. **Rendering** — Headless Chromium renders animated frames from HTML templates
4. **Composition** — FFmpeg assembles frames + audio into the final MP4

## Key Properties

- **Zero-config first run** — generate a video without any API keys using the built-in heuristic script generator and free edge-tts
- **Deterministic** — identical inputs always produce identical output (progress-driven rendering, no real-time timing)
- **Sandboxed** — rendering runs in Chromium with network disabled; LLM data is sanitized before injection
- **Extensible** — custom templates and providers via pip-installable entry points

## Installation

```bash
pip install explainer-studio
playwright install chromium
```

Verify your setup:

```bash
explainer doctor
```

### System Requirements

| Dependency | Purpose | Install |
|---|---|---|
| Python ≥ 3.10 | Runtime | [python.org](https://www.python.org/downloads/) |
| FFmpeg + ffprobe | Video encoding | `brew install ffmpeg` or `apt install ffmpeg` |
| Chromium | Frame rendering | `playwright install chromium` |

### Optional TTS extras

```bash
pip install explainer-studio[elevenlabs]   # ElevenLabs voices
pip install explainer-studio[azure]        # Azure Cognitive Services
pip install explainer-studio[openai]       # OpenAI TTS
```

## Quick Start

Generate a video with one command:

```bash
explainer generate "photosynthesis"
```

Or use the Python API:

```python
from explainer import Pipeline

pipeline = Pipeline()
result = pipeline.generate("photosynthesis")
print(f"Video saved to: {result.mp4_path}")
```

See the [Quick Start guide](quickstart.md) for a step-by-step walkthrough.

## Platform Support

| Platform | Support |
|---|---|
| Linux (x86_64, arm64) | First-class |
| macOS (x86_64, arm64) | First-class |
| Windows | Via WSL — see [Quick Start](quickstart.md#windowswsl-setup) |

## License

MIT — see [LICENSE](https://github.com/pramodthe/explainer-studio/blob/main/LICENSE).
