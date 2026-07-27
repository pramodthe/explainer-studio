# Providers

Explainer Studio uses pluggable providers for LLM (script generation) and TTS (speech synthesis). Providers are discovered at runtime via Python entry points, allowing third-party packages to add support for any service.

---

## LLM Providers

LLM providers generate structured video scripts from a topic string.

### Available Adapters

| Provider | Model String | API Key | Install |
|----------|-------------|---------|---------|
| litellm (any model) | `openai/gpt-5.6`, `gemini/gemini-3.6-flash`, `moonshot/kimi-k3`, etc. | Required (per model) | Included |
| heuristic | — | None | Included |

### Configuration

```bash
# Via environment
export EXPLAINER_LLM=openai/gpt-5.6
export OPENAI_API_KEY=sk-...

# Via CLI flag
explainer generate "topic" --llm openai/gpt-5.6

# Via config file (~/.explainer/config.toml)
[defaults]
llm = "openai/gpt-5.6"
```

### litellm Adapter

The default LLM adapter uses [litellm](https://docs.litellm.ai/) to support 100+ models through a unified interface. Pass any litellm-compatible model string:

```bash
# OpenAI
explainer generate "gravity" --llm openai/gpt-5.6

# Google Gemini
explainer generate "gravity" --llm gemini/gemini-3.6-flash

# Anthropic Claude
explainer generate "gravity" --llm anthropic/claude-sonnet-5

# Any litellm-supported model
explainer generate "gravity" --llm moonshot/kimi-k3
```

#### Current model strings

Scripting is a short, structured, one-shot task, so a mid-tier or fast model is usually
the right trade-off — reserve the flagship tiers for dense technical topics.

| Vendor | Model string | Tier | Required key |
|--------|-------------|------|--------------|
| OpenAI | `openai/gpt-5.6` | Flagship (alias for Sol) | `OPENAI_API_KEY` |
| OpenAI | `openai/gpt-5.6-terra` | Balanced | `OPENAI_API_KEY` |
| OpenAI | `openai/gpt-5.6-luna` | Cost-optimized | `OPENAI_API_KEY` |
| Anthropic | `anthropic/claude-opus-5` | Flagship | `ANTHROPIC_API_KEY` |
| Anthropic | `anthropic/claude-sonnet-5` | Balanced | `ANTHROPIC_API_KEY` |
| Anthropic | `anthropic/claude-haiku-4-5-20251001` | Fast | `ANTHROPIC_API_KEY` |
| Google | `gemini/gemini-3.1-pro-preview` | Flagship reasoning (preview) | `GOOGLE_API_KEY` or `GEMINI_API_KEY` |
| Google | `gemini/gemini-3.6-flash` | Balanced, newest Flash | `GOOGLE_API_KEY` or `GEMINI_API_KEY` |
| Google | `gemini/gemini-3.5-flash-lite` | Cost-optimized | `GOOGLE_API_KEY` or `GEMINI_API_KEY` |
| DeepSeek | `deepseek/deepseek-v4-pro` | Reasoning | `DEEPSEEK_API_KEY` |
| DeepSeek | `deepseek/deepseek-v4-flash` | Low latency | `DEEPSEEK_API_KEY` |
| Moonshot | `moonshot/kimi-k3` | Flagship, 1M context | `MOONSHOT_API_KEY` |

Verified July 2026. Model line-ups move fast — check the vendor's model list if a string
is rejected. Note that DeepSeek retired the legacy `deepseek-chat` and `deepseek-reasoner`
names on 2026-07-24 in favour of the `deepseek-v4-*` identifiers above.

The key that gets validated is chosen from the model string's prefix (see
`_LLM_API_KEY_MAP` in `explainer/config.py`). Google issues a single credential that
different tools name differently, so `gemini/…` and `google/…` accept **either
`GOOGLE_API_KEY` or `GEMINI_API_KEY`** — set whichever name you already have. A bare
`gpt-…` or `claude-…` string without a vendor prefix also resolves correctly.

### Heuristic Fallback

When no LLM is configured, the built-in heuristic generator produces a fixed 4-scene script:

1. `title` — topic name as heading
2. `concept` — placeholder explanation
3. `steps` — placeholder process steps
4. `takeaway` — summary placeholder

This allows generating videos without any API keys (useful for testing and offline use).

---

## TTS Providers

TTS providers synthesize narration audio for each scene.

### Available Adapters

| Provider | Name | API Key | Status |
|----------|------|---------|--------|
| edge-tts | `edge` | None (free) | **Implemented** — the default |
| OpenAI TTS | `openai` | `OPENAI_API_KEY` | **Implemented** — `pip install explainer-studio[openai]` |
| ElevenLabs | `elevenlabs` | — | Not implemented; constructor raises |
| Azure Cognitive | `azure` | — | Not implemented; constructor raises |

`edge` and `openai` synthesise audio. The remaining two names are registered so the
entry-point wiring can be exercised, but their constructors raise. Requesting them fails
at `Pipeline` construction — before any LLM spend — rather than silently falling back to
a different provider.

### OpenAI TTS

Model `gpt-4o-mini-tts`. Voices: `marin` and `cedar` (recommended), plus `alloy`, `ash`,
`ballad`, `coral`, `echo`, `fable`, `nova`, `onyx`, `sage`, `shimmer`, `verse`. Custom
voice ids (`voice_123abc`) pass through untouched.

```bash
export OPENAI_API_KEY=sk-...
explainer generate "topic" --tts openai --voice marin
```

Via the library API you can also steer delivery:

```python
from explainer.providers.tts_openai import OpenAITTSProvider

provider = OpenAITTSProvider(instructions="Speak like a calm documentary narrator.")
```

### Configuration

```bash
# Default (edge-tts, no key needed)
explainer generate "topic"

# Use ElevenLabs
export ELEVENLABS_API_KEY=...
explainer generate "topic" --tts elevenlabs --voice "Rachel"

# Use Azure
export AZURE_SPEECH_KEY=...
export AZURE_SPEECH_REGION=eastus
explainer generate "topic" --tts azure --voice "en-US-JennyNeural"

# Use OpenAI
export OPENAI_API_KEY=sk-...
explainer generate "topic" --tts openai --voice "alloy"
```

### edge-tts (Default)

[edge-tts](https://github.com/rany2/edge-tts) is free, requires no API key, and supports 300+ voices across many languages. It's the default provider for zero-friction first runs.

List available voices:

```bash
explainer voices --lang en
```

### Voice Selection

Each provider has its own voice ID format:

| Provider | Voice ID Example |
|----------|-----------------|
| edge | `en-US-GuyNeural`, `zh-CN-XiaoxiaoNeural` |
| elevenlabs | `Rachel`, `Josh` |
| azure | `en-US-JennyNeural` |
| openai | `alloy`, `echo`, `fable`, `onyx`, `nova`, `shimmer` |

---

## LLM Provider Interface

To create a custom LLM provider, implement the `LLMProvider` protocol:

```python
from explainer.providers.llm_base import LLMProvider, ScriptRequest
from explainer.core.schema import Script


class MyLLMProvider:
    """Satisfies the LLMProvider protocol."""

    def generate_script(self, request: ScriptRequest) -> Script:
        """Generate a validated Script from the request.

        Args:
            request: Contains topic, language, audience, target_duration,
                     and available_templates.

        Returns:
            A validated Script pydantic model instance.

        Raises:
            ScriptValidationError: If output fails validation after retry.
        """
        ...
```

### ScriptRequest Fields

| Field | Type | Description |
|-------|------|-------------|
| `topic` | `str` | The educational topic |
| `language` | `str` | BCP-47 language tag (e.g., `"en"`, `"zh-CN"`) |
| `audience` | `str` | Target audience: `"kid"`, `"student"`, `"adult"` |
| `target_duration` | `int` | Video duration in seconds |
| `available_templates` | `list[TemplateMeta]` | Registered template metadata |

---

## TTS Provider Interface

To create a custom TTS provider, implement the `TTSProvider` protocol:

```python
from pathlib import Path
from explainer.providers.tts_base import TTSProvider, Voice


class MyTTSProvider:
    """Satisfies the TTSProvider protocol."""

    def synthesize(self, text: str, voice: str, out_path: Path) -> float:
        """Convert text to speech and write MP3 to out_path.

        Args:
            text: Narration text to synthesize.
            voice: Provider-specific voice ID.
            out_path: Destination MP3 file path.

        Returns:
            Audio duration in seconds (centisecond precision).

        Raises:
            NarrationError: If synthesis fails after retry.
        """
        ...

    def list_voices(self, language: str) -> list[Voice]:
        """List available voices filtered by language prefix.

        Args:
            language: Language prefix (e.g., "en", "zh-CN").

        Returns:
            List of Voice objects matching the filter.
        """
        ...
```

### Voice Model

```python
from pydantic import BaseModel


class Voice(BaseModel):
    id: str  # Provider-specific voice identifier
    name: str  # Human-readable display name
    language: str  # Language code (e.g., "en-US")
```

---

## Registering Custom Providers

### Package Structure

```
my-explainer-tts/
├── pyproject.toml
└── src/
    └── my_tts/
        ├── __init__.py
        └── provider.py    # Contains MyTTSProvider class
```

### Entry Point Registration

In your package's `pyproject.toml`:

```toml
[project]
name = "my-explainer-tts"
version = "0.1.0"
dependencies = ["explainer-studio"]

[project.entry-points."explainer.providers"]
tts_mycustom = "my_tts.provider:MyTTSProvider"
```

**Naming convention:**

- LLM providers: prefix with `llm_` (e.g., `llm_mycustom`)
- TTS providers: prefix with `tts_` (e.g., `tts_mycustom`)

The entry point value must reference the provider **class** directly.

### Using Your Provider

After `pip install my-explainer-tts`:

```bash
explainer generate "gravity" --tts mycustom
```

Or in Python:

```python
pipeline = Pipeline(tts="mycustom")
```

---

## Provider Resolution Order

Configuration is resolved with the following precedence (highest first):

1. **CLI flags** — `--llm`, `--tts`, `--voice`
2. **Environment variables** — `EXPLAINER_LLM`, `EXPLAINER_TTS`
3. **Config file** — `~/.explainer/config.toml`
4. **Defaults** — no LLM (heuristic), TTS = `edge`

---

## Testing Custom Providers

```bash
# Install in editable mode
pip install -e .

# Verify discovery
explainer doctor

# Test TTS
explainer generate "test topic" --tts mycustom

# Test LLM
explainer generate "test topic" --llm mycustom/model-name

# Run project tests
pytest tests/
```

---

## Error Handling

Providers should handle failures gracefully:

- **Timeout**: LLM calls should time out after 30 seconds. TTS calls should time out after 30 seconds per scene.
- **Retry**: The pipeline retries LLM generation once (appending the validation error) and TTS synthesis once per scene.
- **Exceptions**: Raise `ScriptValidationError` (LLM) or `NarrationError` (TTS) with descriptive messages on unrecoverable failure.
- **API keys**: If a required key is missing, raise `ConfigError` immediately with a message naming the required variable.
