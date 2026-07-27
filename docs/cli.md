# CLI Reference

Explainer Studio provides the `explainer` command after installation.

## `explainer generate`

Generate an explainer video from a topic string.

```bash
explainer generate <topic> [OPTIONS]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `topic` | The educational topic to explain (required) |

### Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--lang` | string | `en` | Language code (BCP-47, e.g., `en`, `zh-CN`, `es`) |
| `--audience` | choice | `student` | Target audience: `kid`, `student`, or `adult` |
| `--duration` | int | `60` | Target video duration in seconds: `30`, `60`, or `90` |
| `--fps` | int | `24` | Frame rate: `15`, `24`, or `30` |
| `--res` | string | `720p` | Resolution: `720p`, `1080p`, or `vertical` (720×1280) |
| `--llm` | string | None | LLM model string (e.g., `openai/gpt-5.6`, `gemini/gemini-3.6-flash`) |
| `--tts` | string | `edge` | TTS provider name: `edge`, `elevenlabs`, `azure`, `openai` |
| `--voice` | string | None | Voice ID (provider-specific) |
| `--music` | path | None | Background music audio file to mix in (ducked to -18dB) |
| `--script` | path | None | Pre-written script JSON file (bypasses LLM generation) |
| `--keep-artifacts` | flag | `false` | Retain intermediate files (script, audio, frames) after completion |
| `-o` / `--output` | path | `./<topic-slug>.mp4` | Output file path |

### Examples

```bash
# Basic usage — no API keys needed
explainer generate "photosynthesis"

# Custom settings
explainer generate "quantum computing" \
  --lang en --audience adult --duration 90 \
  --llm openai/gpt-5.6 --fps 24 --res 1080p \
  -o quantum.mp4

# From existing script
explainer generate "gravity" --script my_script.json

# With background music
explainer generate "solar system" --music bgm.mp3

# Keep working files for debugging
explainer generate "mitosis" --keep-artifacts
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Script generation error |
| 2 | Narration/TTS error |
| 3 | Rendering error |
| 4 | Composition/FFmpeg error |
| 5 | Configuration error |

---

## `explainer doctor`

Check system dependencies and configuration.

```bash
explainer doctor
```

Checks for:

- **FFmpeg** — `ffmpeg` and `ffprobe` on PATH
- **Chromium** — installed via Playwright
- **Providers** — configured LLM and TTS providers
- **Config** — `~/.explainer/config.toml` validity

Prints actionable fix instructions for any missing dependency.

### Example output

```
╭─ System Check ────────────────────────────────╮
│ ✓ ffmpeg       /usr/local/bin/ffmpeg (6.1)    │
│ ✓ ffprobe      /usr/local/bin/ffprobe (6.1)   │
│ ✓ chromium     playwright chromium installed   │
│ ✓ TTS          edge-tts (default, no key)     │
│ ✗ LLM          no provider configured         │
│   → Set EXPLAINER_LLM or run: explainer init  │
╰───────────────────────────────────────────────╯
```

---

## `explainer init`

Interactively create the configuration file at `~/.explainer/config.toml`.

```bash
explainer init
```

Prompts for:

- LLM provider and model string
- TTS provider and voice selection
- API keys (stored in the config file)
- Default resolution and FPS

---

## `explainer templates list`

Display all discovered templates.

```bash
explainer templates list
```

Shows templates from:

- Bundled templates (6 kinds)
- User directory (`~/.explainer/templates/`)
- Installed entry point packages

### Example output

```
┌─────────┬──────────────────────┬─────────┬────────┐
│ Kind    │ Name                 │ Version │ Source │
├─────────┼──────────────────────┼─────────┼────────┤
│ title   │ Title Card           │ 1.0.0   │ built-in│
│ concept │ Concept / Definition │ 1.0.0   │ built-in│
│ steps   │ Step Progression     │ 1.0.0   │ built-in│
│ compare │ Side-by-Side Compare │ 1.0.0   │ built-in│
│ chart   │ Data Chart           │ 1.0.0   │ built-in│
│ takeaway│ Key Takeaways        │ 1.0.0   │ built-in│
└─────────┴──────────────────────┴─────────┴────────┘
```

---

## `explainer templates preview`

Render a template preview at t=0, 0.5, and 1.0.

```bash
explainer templates preview <kind>
```

### Arguments

| Argument | Description |
|----------|-------------|
| `kind` | Template kind to preview (e.g., `concept`, `steps`) |

Outputs a preview image strip or short video showing the template at three progress points.

---

## `explainer voices`

List available TTS voices for the configured provider.

```bash
explainer voices [OPTIONS]
```

### Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--lang` | string | None | Filter voices by language prefix (e.g., `en`, `zh-CN`) |

### Example

```bash
$ explainer voices --lang en
┌────────────────────────┬───────────────────────┬──────────┐
│ ID                     │ Name                  │ Language │
├────────────────────────┼───────────────────────┼──────────┤
│ en-US-GuyNeural        │ Guy (US)              │ en-US    │
│ en-US-JennyNeural      │ Jenny (US)            │ en-US    │
│ en-GB-SoniaNeural      │ Sonia (UK)            │ en-GB    │
│ ...                    │ ...                   │ ...      │
└────────────────────────┴───────────────────────┴──────────┘
```

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `EXPLAINER_LLM` | Default LLM model string |
| `EXPLAINER_TTS` | Default TTS provider name |
| `OPENAI_API_KEY` | API key for OpenAI models and TTS |
| `ELEVENLABS_API_KEY` | API key for ElevenLabs TTS |
| `AZURE_SPEECH_KEY` | API key for Azure Cognitive Services TTS |
| `AZURE_SPEECH_REGION` | Azure region (e.g., `eastus`) |

Environment variables override config file values but are overridden by CLI flags.

---

## Configuration File

Located at `~/.explainer/config.toml`:

```toml
[defaults]
llm = "openai/gpt-5.6"
tts = "edge"
voice = "en-US-GuyNeural"
fps = 24
resolution = "720p"

[keys]
openai = "sk-..."
elevenlabs = "..."
```

Create with `explainer init` or edit manually.
