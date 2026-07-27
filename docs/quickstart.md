# Quick Start

This guide walks you through generating your first explainer video from install to playback.

## Step 1: Install Explainer Studio

```bash
pip install explainer-studio
```

## Step 2: Install the rendering browser

Explainer Studio uses headless Chromium to render animated frames:

```bash
playwright install chromium
```

## Step 3: Verify dependencies

```bash
explainer doctor
```

You should see green checks for FFmpeg, Chromium, and the default TTS provider. If anything is missing, the doctor command prints actionable fix instructions.

## Step 4: Generate your first video

```bash
explainer generate "photosynthesis"
```

This runs the full pipeline:

1. **Script** — the heuristic generator creates a 4-scene structured script (no API key needed)
2. **Narration** — edge-tts synthesizes speech for each scene (free, no signup)
3. **Rendering** — Chromium renders animated frames from the bundled templates
4. **Composition** — FFmpeg encodes frames + audio into the final MP4

The output file is saved to the current directory (e.g., `photosynthesis.mp4`).

!!! tip
    First run may take a few minutes — subsequent runs are faster since Chromium is already installed.

## Step 5: Customize

### Change language, audience, and duration

```bash
explainer generate "black holes" --lang en --audience adult --duration 90
```

### Use a better LLM for script generation

```bash
export OPENAI_API_KEY=sk-...
explainer generate "quantum computing" --llm openai/gpt-5.6
```

### Specify output path

```bash
explainer generate "gravity" -o ~/Videos/gravity_explainer.mp4
```

### Higher quality output

```bash
explainer generate "DNA replication" --fps 24 --res 1080p
```

## Using the Python API

```python
from explainer import Pipeline

# Basic usage
pipeline = Pipeline()
result = pipeline.generate("photosynthesis", language="en")
print(f"Video: {result.mp4_path}")


# With progress tracking
def on_progress(event):
    print(f"[{event.stage}] {event.pct:.0f}% {event.message}")


pipeline = Pipeline(
    llm="openai/gpt-5.6",
    tts="edge",
    on_progress=on_progress,
)
result = pipeline.generate("climate change", audience="adult", target_duration=90)
```

## Using a pre-written script

You can bypass LLM generation by providing a script JSON file:

```bash
explainer generate "gravity" --script my_script.json
```

Script format:

```json
{
  "topic": "gravity",
  "language": "en",
  "audience": "student",
  "scenes": [
    {
      "id": 1,
      "kind": "title",
      "title": "Understanding Gravity",
      "narration": "Let's explore one of nature's fundamental forces.",
      "data": {"subtitle": "A force that shapes the universe"}
    },
    {
      "id": 2,
      "kind": "concept",
      "title": "What is Gravity?",
      "narration": "Gravity is the attractive force between objects with mass.",
      "data": {"bullets": ["Attractive force", "Proportional to mass", "Inversely proportional to distance squared"]}
    },
    {
      "id": 3,
      "kind": "takeaway",
      "title": "Key Takeaways",
      "narration": "Gravity keeps planets in orbit and us on the ground.",
      "data": {"points": ["Universal force", "Shapes the cosmos", "Described by general relativity"]}
    }
  ]
}
```

## Windows/WSL Setup

Explainer Studio runs on Windows through WSL (Windows Subsystem for Linux).

### 1. Install WSL 2

Open PowerShell as Administrator:

```powershell
wsl --install -d Ubuntu-22.04
```

Restart your computer if prompted, then open the Ubuntu terminal.

### 2. Install system dependencies

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv ffmpeg
```

### 3. Install Explainer Studio

```bash
python3.11 -m venv ~/.venvs/explainer
source ~/.venvs/explainer/bin/activate
pip install explainer-studio
playwright install chromium --with-deps
```

The `--with-deps` flag automatically installs Chromium's required system libraries on Ubuntu.

### 4. Generate a video

```bash
# Output to Windows Desktop
explainer generate "photosynthesis" -o /mnt/c/Users/YourName/Desktop/photosynthesis.mp4
```

!!! note
    Replace `YourName` with your Windows username. WSL maps Windows drives under `/mnt/`.

### 5. Verify

```bash
explainer doctor
```

## Next Steps

- [CLI Reference](cli.md) — all commands and flags
- [Python API](api.md) — embed generation in your code
- [Templates](templates.md) — understand and create scene templates
- [Providers](providers.md) — configure LLM and TTS providers
