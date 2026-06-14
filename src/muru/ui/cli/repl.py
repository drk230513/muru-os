"""Interactive REPL (read-eval-print loop) for Muru.

The REPL is the user-facing entry point. It reads natural-language
input, hands it to the Orchestrator, and prints the response.

In v0.3.0+ the REPL:
- Constructs a CliConfirmationProvider that the orchestrator uses
  to ask the user before invoking medium/high/critical risk tools
- Maintains conversation history across turns so multi-step
  reasoning works ("list my Downloads" -> "now show the biggest one")
- Adds a `clear` command to reset history

All existing v0.2.0 commands (help, exit, quit) continue to work.
"""

from __future__ import annotations

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from muru.llm.client import ChatMessage, LLMClient
from muru.orchestrator.orchestrator import Orchestrator
from muru.planner.planner import Planner
from muru.policy.confirmation.cli import CliConfirmationProvider
from muru.tools import filesystem  # noqa: F401 - auto-registers filesystem tools
from muru.tools.registry import registry as default_registry
from muru.utils.logging import get_logger

log = get_logger(__name__)

EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit", ":q"}
HELP_COMMANDS = {"help", "/help", "?"}
CLEAR_COMMANDS = {"clear", "/clear", "reset", "/reset"}


def _print_welcome(console: Console, model: str, tool_count: int) -> None:
    """Print the startup banner."""
    welcome = Panel.fit(
        "[bold cyan]Muru[/bold cyan] [dim]v0.4.0 - filesystem write tools[/dim]\n\n"
        f"Model: [yellow]{model}[/yellow]\n"
        f"Tools loaded: [green]{tool_count}[/green]\n"
        "Type [bold]help[/bold] for commands, [bold]exit[/bold] to quit.\n"
        "[dim]Muru now remembers context across turns and asks "
        "before risky actions.[/dim]",
        title="Welcome",
        border_style="cyan",
    )
    console.print(welcome)


def _print_help(console: Console, tool_names: list[str]) -> None:
    """Print the help message."""
    tools_list = "\n".join(f"  - [cyan]{name}[/cyan]" for name in tool_names)
    help_text = f"""
[bold]Commands:[/bold]
  [cyan]help[/cyan]            Show this message
  [cyan]clear[/cyan]           Clear conversation history (start fresh)
  [cyan]exit[/cyan] / [cyan]quit[/cyan]    Exit Muru

[bold]How to use:[/bold]
  Just type what you want, in plain English. Muru remembers what
  you said earlier in the conversation, so follow-up questions work.

[bold]Available tools:[/bold]
{tools_list}

[bold]Example multi-step session:[/bold]
  you > what files are in my Downloads?
  muru > [lists files]
  you > tell me more about the biggest one
  muru > [reads the file]

[bold]Coming in v0.4.0+:[/bold]
  - Write/edit/delete file tools (with confirmation prompts)
  - Audit log + undo
  - Sandboxed shell access
"""
    console.print(Panel(help_text.strip(), title="Help", border_style="cyan"))


def _read_input(console: Console) -> str:
    """Read one line of input from the user."""
    try:
        return console.input("[bold green]you >[/bold green] ").strip()
    except EOFError:
        return ""


def run_repl(
    client: LLMClient,
    console: Console | None = None,
) -> None:
    """Run the interactive REPL until the user exits.

    Args:
        client: The LLMClient to use for planning and summarization.
        console: Optional Rich Console. Pass a custom one for testing.
    """
    console = console or Console()

    # Build the full stack: planner -> orchestrator -> confirmation
    confirmation_provider = CliConfirmationProvider(console=console)
    planner = Planner(llm=client, registry=default_registry)
    orchestrator = Orchestrator(
        llm=client,
        planner=planner,
        registry=default_registry,
        confirmation_provider=confirmation_provider,
    )

    model = client._resolve_model(None)
    tool_names = default_registry.list_names()
    _print_welcome(console, model, len(tool_names))

    log.info(
        "repl_started",
        model=model,
        tool_count=len(tool_names),
    )

    # Conversation history: user/assistant message turns.
    # System prompts are constructed fresh by the planner each turn.
    history: list[ChatMessage] = []

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
        if lowered in CLEAR_COMMANDS:
            history.clear()
            console.print("[dim]Conversation history cleared.[/dim]")
            log.info("repl_history_cleared")
            continue

        # Hand off to the orchestrator with the current history.
        # Note: we deliberately do NOT wrap this in console.status() because
        # the spinner monopolizes the terminal and interferes with
        # console.input() inside the confirmation provider. With the spinner
        # active, the prompt either gets eaten or input() returns cached
        # terminal content, causing silent auto-approval. The log lines
        # (and the confirmation panel itself for Tier 2+ tools) give the
        # user enough visual feedback.
        try:
            result = orchestrator.handle(user_input, history=list(history))
        except KeyboardInterrupt:
            console.print("\n[dim](interrupted)[/dim]")
            continue
        except Exception as e:
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
        console.print("[bold magenta]muru >[/bold magenta]")

        if result.error:
            console.print(Markdown(result.final_response))
            console.print(f"[dim red]({result.error})[/dim red]")
        else:
            console.print(Markdown(result.final_response))

        console.print()

        # Append to history only on successful, non-error turns.
        # Errored turns are not added so they don't pollute future planning.
        if not result.error:
            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": result.final_response})


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
        force=True,
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
