# Sample Outputs

Videos generated end-to-end by `explainer generate` — LLM script, edge-tts narration,
deterministic Chromium rendering, FFmpeg composition. No hand-editing.

| File | Topic | Script model | Highlights |
| ---- | ----- | ------------ | ---------- |
| `vaccines_sol.mp4` | How do vaccines work | `openai/gpt-5.6-sol` | Best showcase: 4 authored animated diagrams, 24fps, crossfade transitions |
| `water_cycle.mp4` | The water cycle | `openai/gpt-5.5` | 4 animated scenes: evaporation, condensation, rain/runoff, cycle recap |
| `animated_photosynthesis.mp4` | Photosynthesis | `openai/gpt-5.5` | Custom leaf/chloroplast diagrams with stroke-drawn flows |

All clips use the bundled templates plus model-authored `animation` scenes
(see `explainer/prompts/script_system.md` for the authoring contract).

Reproduce the current best with:

```bash
export OPENAI_API_KEY=sk-...
explainer generate "how do vaccines work" --llm openai/gpt-5.6-sol -o out.mp4
```
