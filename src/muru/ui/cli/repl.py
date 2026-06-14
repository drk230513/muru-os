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

from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from muru.llm.client import ChatMessage, LLMClient
from muru.orchestrator.orchestrator import Orchestrator
from muru.planner.planner import Planner
from muru.policy.audit import (
    DEFAULT_AUDIT_FILENAME,
    AuditReader,
    AuditWriter,
    UndoEngine,
)
from muru.policy.confirmation.cli import CliConfirmationProvider
from muru.tools import (
    filesystem,  # noqa: F401 - auto-registers filesystem tools
    shell,  # noqa: F401 - auto-registers shell tools
)
from muru.tools.registry import registry as default_registry
from muru.utils.logging import get_logger

log = get_logger(__name__)

EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit", ":q"}
HELP_COMMANDS = {"help", "/help", "?"}
CLEAR_COMMANDS = {"clear", "/clear", "reset", "/reset"}
HISTORY_COMMANDS = {"history", "/history", "actions", "/actions"}
UNDO_COMMANDS = {"undo", "/undo"}


def _print_welcome(console: Console, model: str, tool_count: int) -> None:
    """Print the startup banner."""
    welcome = Panel.fit(
        "[bold cyan]Muru[/bold cyan] [dim]v0.5.0 - audit log + undo[/dim]\n\n"
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


def _handle_history(console: Console, audit_reader: AuditReader | None) -> None:
    """Show the last 10 audited actions in a table."""
    if audit_reader is None or not audit_reader.exists():
        console.print("[dim]No audit history yet. Run a tool first, then check back.[/dim]")
        return

    entries = audit_reader.recent(n=10)
    if not entries:
        console.print("[dim]No actions in the audit log yet.[/dim]")
        return

    table = Table(title="Recent actions (newest first)", border_style="cyan")
    table.add_column("#", style="dim", width=3)
    table.add_column("When", style="cyan")
    table.add_column("Tool", style="bold")
    table.add_column("Status")
    table.add_column("Intent", overflow="fold")

    for i, entry in enumerate(entries, start=1):
        when = entry.timestamp.strftime("%H:%M:%S")
        if entry.error is not None:
            status = "[red]failed[/red]"
        elif entry.undone:
            status = "[yellow]undone[/yellow]"
        else:
            status = "[green]ok[/green]"
        table.add_row(
            str(i),
            when,
            entry.tool_name,
            status,
            entry.intent[:60],
        )
    console.print(table)


def _handle_undo(
    console: Console,
    audit_reader: AuditReader | None,
    undo_engine: UndoEngine | None,
    audit_writer: AuditWriter | None,
) -> None:
    """Undo the most recent successful action that has not been undone."""
    if audit_reader is None or undo_engine is None or audit_writer is None:
        console.print(
            "[dim]Undo is not available (audit system not configured for this session).[/dim]"
        )
        return

    target = audit_reader.last_undoable()
    if target is None:
        console.print("[dim]Nothing to undo (no successful, un-undone actions in history).[/dim]")
        return

    when = target.timestamp.strftime("%H:%M:%S")
    console.print(
        Panel(
            f"[bold]Will undo:[/bold] [cyan]{target.tool_name}[/cyan] "
            f"at [dim]{when}[/dim]\n"
            f"[bold]Original intent:[/bold] [dim]{target.intent}[/dim]\n"
            f"[bold]Original response:[/bold] [dim]{target.final_response[:200]}[/dim]",
            title="Undo confirmation",
            border_style="yellow",
        )
    )

    try:
        response = (
            console.input("[bold]Proceed with undo?[/bold] [dim](y/n)[/dim] ").strip().lower()
        )
    except (EOFError, KeyboardInterrupt):
        console.print("[dim](cancelled)[/dim]")
        return

    if response not in {"y", "yes"}:
        console.print("[dim]Cancelled. Nothing was undone.[/dim]")
        return

    outcome = undo_engine.undo(target)
    if not outcome.success:
        console.print(
            Panel(
                f"[red]Could not undo:[/red] {outcome.message}",
                title="Undo failed",
                border_style="red",
            )
        )
        return

    # On success: append the undo audit entry, then mark the original undone.
    if outcome.undo_entry is not None:
        try:
            audit_writer.append(outcome.undo_entry)
            audit_writer.mark_undone(
                event_id=str(target.event_id),
                undone_by_event_id=str(outcome.undo_entry.event_id),
            )
        except Exception as e:
            log.warning("undo_audit_failed", error=str(e))

    console.print(
        Panel(
            f"[green]Undone.[/green]\n{outcome.message}",
            title="Undo successful",
            border_style="green",
        )
    )


def run_repl(
    client: LLMClient,
    console: Console | None = None,
    audit_writer: AuditWriter | None = None,
    audit_reader: AuditReader | None = None,
    undo_engine: UndoEngine | None = None,
) -> None:
    """Run the interactive REPL until the user exits.

    Args:
        client: The LLMClient to use for planning and summarization.
        console: Optional Rich Console. Pass a custom one for testing.
        audit_writer: Optional AuditWriter; if provided, tool invocations
            are logged. The REPL `history` and `undo` commands require
            audit_writer + audit_reader + undo_engine to all be present.
        audit_reader: Optional AuditReader for history/undo commands.
        undo_engine: Optional UndoEngine for the undo command.
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
        audit_writer=audit_writer,
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
        if lowered in HISTORY_COMMANDS:
            _handle_history(console, audit_reader)
            continue
        if lowered in UNDO_COMMANDS:
            _handle_undo(console, audit_reader, undo_engine, audit_writer)
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

    # Build audit components rooted at the configured data_dir
    data_dir = Path(config.paths.data_dir).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    audit_path = data_dir / DEFAULT_AUDIT_FILENAME
    audit_writer = AuditWriter(audit_path)
    audit_reader = AuditReader(audit_path)
    undo_engine = UndoEngine(audit_writer)

    try:
        run_repl(
            client,
            console=console,
            audit_writer=audit_writer,
            audit_reader=audit_reader,
            undo_engine=undo_engine,
        )
    except KeyboardInterrupt:
        console.print("\n[dim]Interrupted. Goodbye.[/dim]")
        return 0

    return 0


__all__ = ["main_repl_loop", "run_repl"]
