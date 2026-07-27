# Examples

This directory contains example scripts and usage patterns for Explainer Studio.

## Files

### `photosynthesis_script.json`

A complete Script JSON demonstrating all required fields for the `--script` bypass mode.
Uses four scenes: title → concept → steps → takeaway.

Load it directly with the CLI:

```bash
explainer generate "photosynthesis" --script examples/photosynthesis_script.json
```

Or use it in Python:

```python
from explainer import Script

script = Script.from_file("examples/photosynthesis_script.json")
print(script.topic, len(script.scenes), "scenes")
```

### `basic_usage.py`

Demonstrates using the Pipeline Python API to:

1. Generate a video from a topic string (full pipeline)
2. Render a video from a pre-built Script JSON (skip LLM stage)

Run it:

```bash
# Full pipeline (heuristic LLM + edge-tts)
python examples/basic_usage.py

# From existing script JSON
python examples/basic_usage.py --from-script
```

## Requirements

- `explainer-studio` installed (`pip install -e .`)
- `ffmpeg` and `ffprobe` on PATH
- Playwright Chromium installed (`playwright install chromium`)
- Network access for edge-tts (or use `--tts mock` for offline testing)
