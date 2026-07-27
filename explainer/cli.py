"""CLI entry point for Explainer Studio.

Provides the `explainer` command with subcommands for video generation,
system diagnostics, configuration, template management, and voice listing.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from enum import IntEnum
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)
from rich.prompt import Confirm, Prompt
from rich.table import Table

from explainer.core.errors import (
    CompositionError,
    ConfigError,
    ExplainerError,
    NarrationError,
    RenderError,
    ScriptValidationError,
)

console = Console()

# ---------------------------------------------------------------------------
# Exit codes mapping
# ---------------------------------------------------------------------------


class ExitCode(IntEnum):
    """CLI exit codes per error type."""

    SCRIPT = 1
    NARRATION = 2
    RENDER = 3
    COMPOSITION = 4
    CONFIG = 5


_ERROR_EXIT_MAP: dict[type, int] = {
    ScriptValidationError: ExitCode.SCRIPT,
    NarrationError: ExitCode.NARRATION,
    RenderError: ExitCode.RENDER,
    CompositionError: ExitCode.COMPOSITION,
    ConfigError: ExitCode.CONFIG,
}

_ERROR_SUGGESTIONS: dict[type, str] = {
    ScriptValidationError: "Check your script JSON structure or try a different LLM model.",
    NarrationError: "Verify TTS provider is configured and network is available.",
    RenderError: "Run 'explainer doctor' to check Chromium installation. Check template data schema.",
    CompositionError: "Ensure ffmpeg is installed and on PATH. Run 'explainer doctor'.",
    ConfigError: "Run 'explainer init' to create a valid configuration file.",
}


# ---------------------------------------------------------------------------
# Error display helper
# ---------------------------------------------------------------------------


def _display_error(err: ExplainerError) -> None:
    """Render an ExplainerError as a rich panel with stage, message, and suggestion."""
    error_type = type(err).__name__
    suggestion = _ERROR_SUGGESTIONS.get(
        type(err), "Check the error message for details."
    )

    content = (
        f"[bold]Stage:[/bold] {err.stage}\n"
        f"[bold]Error:[/bold] {err.message}\n\n"
        f"[dim]Suggestion:[/dim] {suggestion}"
    )

    console.print(
        Panel(
            content,
            title=f"[red]{error_type}[/red]",
            border_style="red",
            expand=False,
        )
    )


def _get_exit_code(err: ExplainerError) -> int:
    """Return the exit code for a given error type."""
    return _ERROR_EXIT_MAP.get(type(err), 1)


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="explainer",
    help="Generate educational explainer videos from a topic string.",
    no_args_is_help=True,
)

# Templates sub-app
templates_app = typer.Typer(
    name="templates",
    help="Manage and preview templates.",
    no_args_is_help=True,
)
app.add_typer(templates_app, name="templates")


# ---------------------------------------------------------------------------
# generate command
# ---------------------------------------------------------------------------


@app.command()
def generate(
    topic: str = typer.Argument(..., help="Topic to explain"),
    lang: str = typer.Option("en", "--lang", help="Language code (e.g. en, zh, es)"),
    audience: str = typer.Option(
        "student", "--audience", help="Target audience: kid, student, or adult"
    ),
    duration: int = typer.Option(
        60, "--duration", help="Target duration in seconds (30/60/90)"
    ),
    fps: int = typer.Option(15, "--fps", help="Frames per second (15/24/30)"),
    res: str = typer.Option(
        "720p", "--res", help="Resolution: 720p, 1080p, or vertical"
    ),
    llm: str | None = typer.Option(None, "--llm", help="LLM model string"),
    tts: str = typer.Option("edge", "--tts", help="TTS provider name"),
    voice: str | None = typer.Option(None, "--voice", help="Voice ID for TTS"),
    music: Path | None = typer.Option(
        None, "--music", help="Background music audio file"
    ),
    script: Path | None = typer.Option(
        None, "--script", help="Pre-built script JSON (bypasses LLM)"
    ),
    keep_artifacts: bool = typer.Option(
        False, "--keep-artifacts", help="Keep work directory after completion"
    ),
    out: Path | None = typer.Option(None, "-o", "--out", help="Output MP4 file path"),
) -> None:
    """Generate an explainer video from a topic string."""
    from explainer.core.pipeline import Pipeline, ProgressEvent
    from explainer.core.schema import Script as ScriptModel

    try:
        # Set up progress bar
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task_id = progress.add_task("Initializing...", total=100)

            def on_progress(event: ProgressEvent) -> None:
                """Update rich progress bar from pipeline events."""
                label = event.message or f"Stage: {event.stage}"
                progress.update(task_id, completed=event.pct, description=label)

            pipeline = Pipeline(
                llm=llm,
                tts=tts,
                voice=voice,
                on_progress=on_progress,
            )

            music_str = str(music) if music else None
            out_str = str(out) if out else None

            if script is not None:
                # --script bypass: load Script from file and call Pipeline.render()
                script_obj = ScriptModel.from_file(script)
                result = pipeline.render(
                    script_obj,
                    out=out_str,
                    fps=fps,
                    resolution=res,
                    music=music_str,
                    keep_artifacts=keep_artifacts,
                    on_progress=on_progress,
                )
            else:
                # Full pipeline generation
                result = pipeline.generate(
                    topic,
                    language=lang,
                    audience=audience,
                    target_duration=duration,
                    fps=fps,
                    resolution=res,
                    music=music_str,
                    out=out_str,
                    keep_artifacts=keep_artifacts,
                )

        console.print(
            f"\n[green bold]✓[/green bold] Video saved to: [cyan]{result.mp4_path}[/cyan]"
        )

    except ExplainerError as err:
        _display_error(err)
        raise typer.Exit(code=_get_exit_code(err)) from err


# ---------------------------------------------------------------------------
# doctor command
# ---------------------------------------------------------------------------


@app.command()
def doctor() -> None:
    """Check system dependencies and configuration."""
    console.print("[bold]Explainer Studio — System Check[/bold]\n")
    all_ok = True

    # Check ffmpeg
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            version_line = result.stdout.split("\n")[0] if result.stdout else "unknown"
            console.print(f"  [green]✓[/green] ffmpeg: {version_line}")
        except (subprocess.TimeoutExpired, OSError):
            console.print("  [red]✗[/red] ffmpeg: found but failed to execute")
            all_ok = False
    else:
        console.print("  [red]✗[/red] ffmpeg: not found on PATH")
        console.print(
            "    [dim]Fix: Install ffmpeg (brew install ffmpeg / apt install ffmpeg)[/dim]"
        )
        all_ok = False

    # Check ffprobe
    ffprobe_path = shutil.which("ffprobe")
    if ffprobe_path:
        console.print(f"  [green]✓[/green] ffprobe: {ffprobe_path}")
    else:
        console.print("  [red]✗[/red] ffprobe: not found on PATH")
        console.print(
            "    [dim]Fix: ffprobe ships with ffmpeg — reinstall ffmpeg[/dim]"
        )
        all_ok = False

    # Check Chromium via Playwright
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "--dry-run", "chromium"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode == 0:
            console.print("  [green]✓[/green] Chromium (Playwright): installed")
        else:
            # --dry-run may not be supported; try checking if chromium path exists
            _check_chromium_fallback()
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        _check_chromium_fallback()

    # Check config file
    from explainer.config import DEFAULT_CONFIG_PATH

    if DEFAULT_CONFIG_PATH.is_file():
        console.print(f"  [green]✓[/green] Config: {DEFAULT_CONFIG_PATH}")
    else:
        console.print(
            f"  [yellow]○[/yellow] Config: {DEFAULT_CONFIG_PATH} (not found, using defaults)"
        )
        console.print(
            "    [dim]Fix: Run 'explainer init' to create a config file[/dim]"
        )

    console.print()
    if all_ok:
        console.print("[green bold]All checks passed![/green bold]")
    else:
        console.print("[yellow]Some issues found. See suggestions above.[/yellow]")


def _check_chromium_fallback() -> None:
    """Fallback check for Chromium installation."""
    if importlib.util.find_spec("playwright") is None:
        console.print("  [red]✗[/red] Chromium (Playwright): not installed")
        console.print(
            "    [dim]Fix: pip install playwright && playwright install chromium[/dim]"
        )
        return

    if importlib.util.find_spec("playwright._impl._driver") is not None:
        console.print("  [green]✓[/green] Chromium (Playwright): package installed")
    else:
        console.print(
            "  [yellow]○[/yellow] Chromium (Playwright): package installed, browser status unknown"
        )
        console.print("    [dim]Fix: Run 'playwright install chromium'[/dim]")


# ---------------------------------------------------------------------------
# init command
# ---------------------------------------------------------------------------


@app.command()
def init() -> None:
    """Interactively create ~/.explainer/config.toml."""
    from explainer.config import DEFAULT_CONFIG_PATH

    console.print("[bold]Explainer Studio — Configuration Setup[/bold]\n")

    if DEFAULT_CONFIG_PATH.is_file():
        overwrite = Confirm.ask(
            f"Config file already exists at {DEFAULT_CONFIG_PATH}. Overwrite?",
            default=False,
        )
        if not overwrite:
            console.print("[yellow]Aborted.[/yellow]")
            raise typer.Exit()

    # Prompt for LLM model
    llm_model = Prompt.ask(
        "LLM model string (e.g. openai/gpt-5.6, leave blank for heuristic fallback)",
        default="",
    )

    # Prompt for TTS provider
    tts_provider = Prompt.ask(
        "TTS provider (edge, elevenlabs, azure, openai)",
        default="edge",
    )

    # Prompt for voice
    voice_id = Prompt.ask(
        "Default voice ID (leave blank for provider default)",
        default="",
    )

    # Prompt for API keys if needed
    api_keys: dict[str, str] = {}
    if llm_model and not llm_model.startswith("heuristic"):
        key_name = _guess_api_key_name(llm_model)
        if key_name:
            key_value = Prompt.ask(
                f"API key for {key_name} (leave blank to set via env var later)",
                default="",
            )
            if key_value:
                api_keys[key_name] = key_value

    if tts_provider in ("elevenlabs", "azure", "openai"):
        tts_key_map = {
            "elevenlabs": "ELEVENLABS_API_KEY",
            "azure": "AZURE_SPEECH_KEY",
            "openai": "OPENAI_API_KEY",
        }
        key_name = tts_key_map[tts_provider]
        if key_name not in api_keys:
            key_value = Prompt.ask(
                f"API key for {key_name} (leave blank to set via env var later)",
                default="",
            )
            if key_value:
                api_keys[key_name] = key_value

    # Build TOML content
    lines = ["# Explainer Studio configuration", ""]
    if llm_model:
        lines.append(f'llm = "{llm_model}"')
    lines.append(f'tts = "{tts_provider}"')
    if voice_id:
        lines.append(f'voice = "{voice_id}"')
    lines.append("fps = 15")
    lines.append('resolution = "720p"')
    lines.append("keep_artifacts = false")

    if api_keys:
        lines.append("")
        lines.append("[api_keys]")
        for key, value in api_keys.items():
            lines.append(f'{key} = "{value}"')

    lines.append("")

    # Write config file
    DEFAULT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_CONFIG_PATH.write_text("\n".join(lines), encoding="utf-8")

    console.print(
        f"\n[green bold]✓[/green bold] Config saved to: [cyan]{DEFAULT_CONFIG_PATH}[/cyan]"
    )


def _guess_api_key_name(model: str) -> str | None:
    """Guess the API key env var name from a model string."""
    model_lower = model.lower()
    prefixes = {
        "openai": "OPENAI_API_KEY",
        "gpt": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "claude": "ANTHROPIC_API_KEY",
        "gemini": "GOOGLE_API_KEY",
        "google": "GOOGLE_API_KEY",
        "moonshot": "MOONSHOT_API_KEY",
        "kimi": "MOONSHOT_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
    }
    for prefix, key in prefixes.items():
        if model_lower.startswith(prefix):
            return key
    return None


# ---------------------------------------------------------------------------
# templates list command
# ---------------------------------------------------------------------------


@templates_app.command("list")
def templates_list() -> None:
    """List all discovered templates."""
    from explainer.core.registry import Registry

    try:
        registry = Registry()
        registry.discover()
        templates = registry.list_templates()

        if not templates:
            console.print("[yellow]No templates found.[/yellow]")
            console.print("[dim]Templates are discovered from:[/dim]")
            console.print("[dim]  - explainer/templates/ (bundled)[/dim]")
            console.print("[dim]  - ~/.explainer/templates/ (user)[/dim]")
            console.print("[dim]  - entry points (explainer.templates)[/dim]")
            raise typer.Exit()

        table = Table(title="Discovered Templates")
        table.add_column("Kind", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Version", style="dim")

        for tmpl in templates:
            table.add_row(tmpl.kind.value, tmpl.name, tmpl.version)

        console.print(table)

    except ExplainerError as err:
        _display_error(err)
        raise typer.Exit(code=_get_exit_code(err)) from err


# ---------------------------------------------------------------------------
# templates preview command
# ---------------------------------------------------------------------------


@templates_app.command("preview")
def templates_preview(
    kind: str = typer.Argument(
        ..., help="Template kind to preview (e.g. concept, steps)"
    ),
) -> None:
    """Render a template at t=0, 0.5, 1.0 to preview images."""
    from explainer.core.registry import Registry
    from explainer.core.schema import SceneKind

    try:
        # Validate kind
        try:
            scene_kind = SceneKind(kind)
        except ValueError:
            valid_kinds = ", ".join(k.value for k in SceneKind)
            console.print(f"[red]Invalid template kind '{kind}'.[/red]")
            console.print(f"[dim]Valid kinds: {valid_kinds}[/dim]")
            raise typer.Exit(code=1) from None

        registry = Registry()
        registry.discover()

        try:
            template = registry.get_template(scene_kind)
        except KeyError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1) from exc

        console.print(
            f"[bold]Previewing template: {template.name} ({template.kind.value})[/bold]\n"
        )

        # Render at t=0, 0.5, 1.0 using Playwright
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            console.print("[red]Playwright not installed.[/red]")
            console.print(
                "[dim]Fix: pip install playwright && playwright install chromium[/dim]"
            )
            raise typer.Exit(code=1) from None

        preview_dir = Path.cwd() / f"preview_{kind}"
        preview_dir.mkdir(parents=True, exist_ok=True)

        t_values = [0.0, 0.5, 1.0]
        sample_scene_data: dict[str, object] = {}  # Empty data for preview

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 720})

            page.goto(f"file://{template.index_html}")
            page.evaluate(
                f"window.setSceneData({json.dumps(sample_scene_data)}, {json.dumps(template.default_style)})"
            )

            for t in t_values:
                page.evaluate(f"window.renderFrame({t})")
                filename = f"t_{t:.1f}.png"
                page.screenshot(path=str(preview_dir / filename))
                console.print(f"  [green]✓[/green] Saved {preview_dir / filename}")

            browser.close()

        console.print(
            f"\n[green bold]✓[/green bold] Preview images saved to: [cyan]{preview_dir}[/cyan]"
        )

    except ExplainerError as err:
        _display_error(err)
        raise typer.Exit(code=_get_exit_code(err)) from err


# ---------------------------------------------------------------------------
# voices command
# ---------------------------------------------------------------------------


@app.command()
def voices(
    lang: str = typer.Option("en", "--lang", help="Filter voices by language code"),
) -> None:
    """List available voices from the configured TTS provider."""
    try:
        from explainer.config import ExplainerConfig

        config = ExplainerConfig.resolve()
        tts_name = config.tts

        # Load appropriate TTS provider
        if tts_name == "edge":
            from explainer.providers.tts_edge import EdgeTTSProvider

            provider = EdgeTTSProvider()
        else:
            # Fallback to edge for listing
            from explainer.providers.tts_edge import EdgeTTSProvider

            provider = EdgeTTSProvider()
            console.print(
                f"[dim]Note: Using edge-tts voice list (provider '{tts_name}' voice listing may not be available)[/dim]\n"
            )

        voice_list = provider.list_voices(language=lang)

        if not voice_list:
            console.print(f"[yellow]No voices found for language '{lang}'.[/yellow]")
            raise typer.Exit()

        table = Table(title=f"Available Voices (lang={lang})")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Language", style="dim")

        for v in voice_list:
            table.add_row(v.id, v.name, v.language)

        console.print(table)
        console.print(f"\n[dim]Total: {len(voice_list)} voices[/dim]")

    except ExplainerError as err:
        _display_error(err)
        raise typer.Exit(code=_get_exit_code(err)) from err


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()
