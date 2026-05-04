"""Interactive REPL (read-eval-print loop) for Muru.

The REPL is the user-facing entry point. It reads natural-language input,
hands it to the Orchestrator, and prints the response.

In v0.1.0 this was a simple LLM chat loop. In v0.2.0+ the REPL routes
every intent through the planner+executor pipeline, so Muru can call
real tools (filesystem operations, etc.) when the LLM decides one is
needed.

Usage:
    from muru.ui.cli.repl import run_repl
    from muru.llm.client import LLMClient
    from muru.utils.config import load_config

    config = load_config()
    client = LLMClient(config.llm)
    run_repl(client)
"""

from __future__ import annotations

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from muru.llm.client import LLMClient
from muru.orchestrator.orchestrator import Orchestrator
from muru.planner.planner import Planner
from muru.tools import filesystem  # noqa: F401  — auto-registers filesystem tools
from muru.tools.registry import registry as default_registry
from muru.utils.logging import get_logger

log = get_logger(__name__)


# Special commands the REPL handles directly (not sent to the orchestrator).
EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit", ":q"}
HELP_COMMANDS = {"help", "/help", "?"}


def _print_welcome(console: Console, model: str, tool_count: int) -> None:
    """Print the startup banner."""
    welcome = Panel.fit(
        "[bold cyan]Muru[/bold cyan] [dim]v0.2.0 — read-only tool release[/dim]\n\n"
        f"Model: [yellow]{model}[/yellow]\n"
        f"Tools loaded: [green]{tool_count}[/green]\n"
        "Type [bold]help[/bold] for commands, [bold]exit[/bold] to quit.\n"
        "[dim]Muru can now read files, list directories, and search content.[/dim]",
        title="🌱 Welcome",
        border_style="cyan",
    )
    console.print(welcome)


def _print_help(console: Console, tool_names: list[str]) -> None:
    """Print the help message."""
    tools_list = "\n".join(f"  • [cyan]{name}[/cyan]" for name in tool_names)
    help_text = f"""
[bold]Commands:[/bold]
  [cyan]help[/cyan]            Show this message
  [cyan]exit[/cyan] / [cyan]quit[/cyan]    Exit Muru

[bold]How to use:[/bold]
  Just type what you want, in plain English. Muru will decide whether
  to respond directly or call one of its tools to look something up.

[bold]Available tools:[/bold]
{tools_list}

[bold]Example questions:[/bold]
  • What python files are in my muru-os/src folder?
  • Find files containing the word "Pydantic" in muru-os
  • Show me the contents of my README.md
  • What does the file ~/notes.txt contain?

[bold]Coming in v0.3.0+:[/bold]
  - Risk classification + confirmation engine
  - Audit log + undo
  - Sandboxed shell access
"""
    console.print(Panel(help_text.strip(), title="Help", border_style="cyan"))


def _read_input(console: Console) -> str:
    """Read one line of input from the user."""
    try:
        return console.input("[bold green]you ›[/bold green] ").strip()
    except EOFError:
        return ""


def run_repl(
    client: LLMClient,
    console: Console | None = None,
) -> None:
    """Run the interactive REPL until the user exits.

    Args:
        client: The LLMClient to use for both planning and summarization.
        console: Optional Rich Console. If None, creates a default one.
            Pass a custom console for testing.
    """
    console = console or Console()

    # Build the orchestrator stack
    planner = Planner(llm=client, registry=default_registry)
    orchestrator = Orchestrator(
        llm=client,
        planner=planner,
        registry=default_registry,
    )

    model = client._resolve_model(None)
    tool_names = default_registry.list_names()
    _print_welcome(console, model, len(tool_names))

    log.info("repl_started", model=model, tool_count=len(tool_names))

    while True:
        user_input = _read_input(console)

        if not user_input:
            console.print("[dim](use 'exit' to quit)[/dim]")
            continue

        lowered = user_input.lower()
        if lowered in EXIT_COMMANDS:
            console.print("[dim]Goodbye.[/dim]")
            log.info("repl_exited", reason="user_command")
            return
        if lowered in HELP_COMMANDS:
            _print_help(console, tool_names)
            continue

        # Hand off to the orchestrator
        try:
            with console.status("[dim]Muru is thinking...[/dim]", spinner="dots"):
                result = orchestrator.handle(user_input)
        except KeyboardInterrupt:
            console.print("\n[dim](interrupted)[/dim]")
            continue
        except Exception as e:
            # Orchestrator should not raise, but defend against bugs
            log.error("repl_orchestrator_unhandled_exception", error=str(e))
            console.print(
                Panel(
                    f"[red]Unexpected error:[/red] {e}\n\n"
                    "[dim]This is a bug. Please report it.[/dim]",
                    title="Error",
                    border_style="red",
                )
            )
            continue

        # Render the response
        console.print()
        console.print("[bold magenta]muru ›[/bold magenta]")

        if result.error:
            # Show errors in a different color but keep the friendly message
            console.print(Markdown(result.final_response))
            console.print(f"[dim red]({result.error})[/dim red]")
        else:
            console.print(Markdown(result.final_response))

        console.print()


def main_repl_loop() -> int:
    """Top-level entry: load config, build client, run REPL.

    Returns:
        Exit code (0 = clean exit, 1 = startup failure).
    """
    from muru.utils.config import load_config
    from muru.utils.logging import configure_logging

    console = Console()

    try:
        config = load_config()
    except Exception as e:
        console.print(f"[red]Failed to load config:[/red] {e}")
        return 1

    configure_logging(
        level=config.logging.level,
        json_output=(config.logging.format == "json"),
        log_file=config.logging.file or None,
    )

    client = LLMClient(config.llm)

    if not client.is_available():
        console.print(
            Panel(
                f"[red]Cannot reach Ollama at {config.llm.host}[/red]\n\n"
                "Is Ollama running? Try:\n"
                "  [cyan]sudo systemctl status ollama[/cyan]\n\n"
                "If not running:\n"
                "  [cyan]sudo systemctl start ollama[/cyan]",
                title="Connection Error",
                border_style="red",
            )
        )
        return 1

    try:
        run_repl(client, console=console)
    except KeyboardInterrupt:
        console.print("\n[dim]Interrupted. Goodbye.[/dim]")
        return 0

    return 0


__all__ = ["main_repl_loop", "run_repl"]
