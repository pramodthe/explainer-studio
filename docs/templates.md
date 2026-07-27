# Template System

Templates are the visual building blocks of explainer videos. Each scene in a video is rendered by a template that produces animated frames from structured data.

## How Templates Work

A template is a self-contained HTML/JS directory that:

1. Receives scene data via `window.setSceneData(data, style)`
2. Renders any frame by progress value via `window.renderFrame(t)` where `t ∈ [0, 1]`

The renderer captures a screenshot after each `renderFrame(t)` call, stepping `t` uniformly from 0 to 1 based on the scene's audio duration and configured FPS.

---

## Bundled Templates

Explainer Studio ships with six template kinds:

| Kind | Purpose | Typical Data |
|------|---------|--------------|
| `title` | Opening title card with animated subtitle | `subtitle`, `author` |
| `concept` | Diagram + bullet explanations | `bullets`, `diagram` (type + labels) |
| `steps` | Ordered step progression with connectors | `steps` (array of step objects) |
| `compare` | Two-column side-by-side comparison | `left`, `right` (arrays of items) |
| `chart` | Animated bar or line chart | `type`, `labels`, `values` |
| `takeaway` | Key points summary with sequential reveals | `points` (array of strings) |

List discovered templates:

```bash
explainer templates list
```

Preview a template:

```bash
explainer templates preview concept
```

---

## Template Directory Structure

```
my_template/
├── template.json     # Metadata + data JSON Schema
├── index.html        # Self-contained renderer
└── preview.png       # Gallery thumbnail (optional)
```

### `template.json`

```json
{
  "kind": "concept",
  "name": "Concept / Definition",
  "version": "1.0.0",
  "schema": {
    "type": "object",
    "properties": {
      "bullets": {
        "type": "array",
        "items": { "type": "string" }
      },
      "diagram": {
        "type": "object",
        "properties": {
          "type": { "type": "string", "enum": ["triangle", "cycle", "flow"] },
          "labels": { "type": "array", "items": { "type": "string" } }
        }
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

| Field | Description |
|-------|-------------|
| `kind` | One of: `title`, `concept`, `steps`, `compare`, `chart`, `takeaway`, `animation` |
| `name` | Human-readable display name |
| `version` | Semver string |
| `schema` | JSON Schema for the `data` object passed to `setSceneData` |
| `default_style` | Default style values (can be overridden) |

### `index.html` Contract

The HTML file must expose two global functions:

```js
// Called once before frame capture begins.
// Populate the DOM with scene content.
window.setSceneData = function(data, style) {
    // data: matches the "schema" in template.json
    // style: merged default_style + any overrides
};

// Called per frame. Render the visual state at progress t.
// MUST be a pure function of t — deterministic output.
window.renderFrame = function(t) {
    // t = 0: start of scene
    // t = 1: end of scene
    // Animate elements based on t
};
```

---

## Template Rules

Templates must follow these rules for correct, deterministic rendering:

### Self-contained

- All CSS, JS, SVG, and assets must be inline
- No external network requests (fetch, XHR, WebSocket)
- No external `src` or `href` attributes
- No external fonts or stylesheets

### Deterministic

- Same `data` + same `t` must produce identical pixels
- No `Date.now()` or `performance.now()`
- No unseeded `Math.random()`
- No `requestAnimationFrame`-based timing
- No CSS animations with real-time durations

### Fixed viewport

- Design for 1280×720 (720p) as the base resolution
- The renderer also supports 1920×1080 (1080p) and 720×1280 (vertical)
- Use relative units or SVG viewBox for scalability

---

## Authoring a Custom Template

### Step 1: Create the directory

```
my_concept/
├── __init__.py
├── template.json
├── index.html
└── preview.png
```

### Step 2: Define the schema

Write `template.json` specifying what data your template accepts:

```json
{
  "kind": "concept",
  "name": "My Custom Concept",
  "version": "1.0.0",
  "schema": {
    "type": "object",
    "properties": {
      "heading": { "type": "string" },
      "items": { "type": "array", "items": { "type": "string" } }
    },
    "required": ["heading", "items"]
  },
  "default_style": {
    "bg": "#1a1a2e",
    "accent": "#e94560",
    "font": "sans-serif"
  }
}
```

### Step 3: Implement the renderer

Create `index.html`:

```html
<!DOCTYPE html>
<html>
<head>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { width: 1280px; height: 720px; overflow: hidden; font-family: sans-serif; }
  .container { width: 100%; height: 100%; display: flex; flex-direction: column;
               justify-content: center; align-items: center; padding: 60px; }
  h1 { font-size: 48px; color: white; margin-bottom: 40px; }
  .item { font-size: 28px; color: #ccc; margin: 12px 0; opacity: 0; }
</style>
</head>
<body>
<div class="container" id="stage"></div>
<script>
let sceneData = {};
let sceneStyle = {};

window.setSceneData = function(data, style) {
    sceneData = data;
    sceneStyle = style;
    document.body.style.background = style.bg || '#1a1a2e';

    const stage = document.getElementById('stage');
    stage.innerHTML = `<h1>${data.heading}</h1>` +
        data.items.map((item, i) =>
            `<div class="item" id="item-${i}">${item}</div>`
        ).join('');
};

window.renderFrame = function(t) {
    const items = sceneData.items || [];
    items.forEach((_, i) => {
        const el = document.getElementById(`item-${i}`);
        if (!el) return;
        // Stagger reveal: each item appears at t = i / items.length
        const threshold = i / items.length;
        const progress = Math.max(0, Math.min(1, (t - threshold) * items.length));
        el.style.opacity = progress;
        el.style.transform = `translateY(${(1 - progress) * 20}px)`;
    });
};
</script>
</body>
</html>
```

### Step 4: Add the entry point module

Create `__init__.py`:

```python
from pathlib import Path


def get_path() -> Path:
    """Return the path to this template's directory."""
    return Path(__file__).parent
```

### Step 5: Register via pyproject.toml

```toml
[project.entry-points."explainer.templates"]
my_concept = "my_package.my_concept:get_path"
```

After `pip install`, the template is automatically discovered by the registry.

---

## Template Discovery

Templates are discovered from three sources (in order):

1. **Bundled** — `explainer/templates/*` (the 6 built-in kinds)
2. **User directory** — `~/.explainer/templates/` (local overrides)
3. **Entry points** — `explainer.templates` group from installed packages

To install a template locally without packaging:

```bash
mkdir -p ~/.explainer/templates/my_concept
# Copy template.json, index.html, preview.png into the directory
```

---

## Helper Functions

Common animation utilities used in the bundled templates:

```js
// Easing function (ease-in-out)
function ease(t) {
    return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
}

// Clamp value to [min, max]
function clamp(val, min, max) {
    return Math.max(min, Math.min(max, val));
}

// Sub-progress window: maps global t to a local [0,1] within [start, end]
function seg(t, start, end) {
    return clamp((t - start) / (end - start), 0, 1);
}

// Linear interpolation
function lerp(a, b, t) {
    return a + (b - a) * t;
}
```

---

## Validation

Templates are validated at discovery time:

- `template.json` must be parseable and contain required fields (`kind`, `name`, `version`, `schema`)
- `index.html` must exist in the template directory
- `index.html` must not reference external URLs in `src` or `href` attributes

Templates that fail validation are skipped with a warning logged.

Scene data is validated against the template's JSON Schema before rendering begins. If validation fails, `ScriptValidationError` is raised.

---

## Testing Templates

```bash
# Check discovery
explainer templates list

# Visual preview
explainer templates preview my_concept

# Full video test
explainer generate "test topic" --llm heuristic
```

For automated testing, render at t=0, t=0.5, t=1.0 and compare against baseline screenshots.
