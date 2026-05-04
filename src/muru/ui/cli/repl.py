"""Interactive REPL (read-eval-print loop) for Muru.

The REPL reads natural-language input from the user, sends it to the LLM,
and prints the response. This is the v0.1.0 placeholder for what will
eventually become a sophisticated planner + tool execution loop.

For now, the LLM responds in pure conversational mode — no tool execution,
no risk classification, no confirmation. Those land in v0.2.0+.

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
from muru.llm.exceptions import LLMError
from muru.utils.logging import get_logger

log = get_logger(__name__)


# System message gives the LLM context about who it is and how to behave.
# Will become much more sophisticated in v0.2.0+ when we add tools.
DEFAULT_SYSTEM_MESSAGE = """You are Muru, an AI-native operating system assistant.

You are currently in your foundation release (v0.1.0). You can hold a
conversation but cannot yet execute actions on the user's computer —
that capability is coming in future versions.

Be concise, friendly, and direct. If a user asks you to do something
that requires running commands or modifying files, explain that those
capabilities are not yet enabled but will be added in upcoming versions."""

# Special commands the REPL handles directly (not sent to the LLM).
EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit", ":q"}
HELP_COMMANDS = {"help", "/help", "?"}


def _print_welcome(console: Console, model: str) -> None:
    """Print the startup banner."""
    welcome = Panel.fit(
        "[bold cyan]Muru[/bold cyan] [dim]v0.1.0 — foundation release[/dim]\n\n"
        f"Model: [yellow]{model}[/yellow]\n"
        "Type [bold]help[/bold] for commands, [bold]exit[/bold] to quit.\n"
        "[dim]Note: tool execution lands in v0.2.0+. For now, conversation only.[/dim]",
        title="🌱 Welcome",
        border_style="cyan",
    )
    console.print(welcome)


def _print_help(console: Console) -> None:
    """Print the help message."""
    help_text = """
[bold]Commands:[/bold]
  [cyan]help[/cyan]            Show this message
  [cyan]exit[/cyan] / [cyan]quit[/cyan]    Exit Muru

[bold]How to use:[/bold]
  Just type what you want, in plain English. Muru will respond.
  Multi-line input not supported yet — one line at a time.

[bold]Coming in v0.2.0+:[/bold]
  - File operations (read, list, search)
  - Risk classification + confirmation engine
  - Audit log + undo
  - Sandboxed shell access
"""
    console.print(Panel(help_text.strip(), title="Help", border_style="cyan"))


def _read_input(console: Console) -> str:
    """Read one line of input from the user.

    Returns the trimmed input string. Returns empty string on EOF (Ctrl-D)
    so the caller can exit gracefully.
    """
    try:
        # Rich's input() handles colored prompts properly across terminals
        return console.input("[bold green]you ›[/bold green] ").strip()
    except EOFError:
        return ""


def run_repl(
    client: LLMClient,
    system_message: str | None = None,
    console: Console | None = None,
) -> None:
    """Run the interactive REPL until the user exits.

    Args:
        client: The LLMClient to send messages to.
        system_message: Optional override for the system message. If None,
            uses DEFAULT_SYSTEM_MESSAGE.
        console: Optional Rich Console. If None, creates a default one.
            Pass a custom console for testing.
    """
    console = console or Console()
    system = system_message if system_message is not None else DEFAULT_SYSTEM_MESSAGE

    model = client._resolve_model(None)  # The default-profile model
    _print_welcome(console, model)

    log.info("repl_started", model=model)

    # Conversation history — grows as the user and assistant exchange messages.
    # In v0.1.0 we keep this simple: just user/assistant turns, plus the
    # initial system message. v0.2.0+ adds context summarization for long chats.
    history: list[dict[str, str]] = [{"role": "system", "content": system}]

    while True:
        user_input = _read_input(console)

        # Empty input (or EOF) — ask again, or exit on EOF
        if not user_input:
            console.print("[dim](use 'exit' to quit)[/dim]")
            continue

        # Handle built-in commands without calling the LLM
        lowered = user_input.lower()
        if lowered in EXIT_COMMANDS:
            console.print("[dim]Goodbye.[/dim]")
            log.info("repl_exited", reason="user_command")
            return
        if lowered in HELP_COMMANDS:
            _print_help(console)
            continue

        # Append user message to history
        history.append({"role": "user", "content": user_input})

        # Send the whole history to the LLM (system + all turns so far)
        try:
            with console.status("[dim]Muru is thinking...[/dim]", spinner="dots"):
                response = client.chat(history)
        except LLMError as e:
            console.print(
                Panel(
                    f"[red]LLM error:[/red] {e}\n\n"
                    "[dim]Your message was not added to history. Try again.[/dim]",
                    title="Error",
                    border_style="red",
                )
            )
            # Roll back the user message — it never got a response
            history.pop()
            continue
        except KeyboardInterrupt:
            console.print("\n[dim](interrupted — message not sent)[/dim]")
            history.pop()
            continue

        # Append assistant response to history so it has context next turn
        history.append({"role": "assistant", "content": response})

        # Render assistant response with markdown formatting
        # (LLMs often produce markdown — bold, lists, code blocks)
        console.print()
        console.print("[bold magenta]muru ›[/bold magenta]")
        console.print(Markdown(response))
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

    # Configure logging based on user's config
    configure_logging(
        level=config.logging.level,
        json_output=(config.logging.format == "json"),
        log_file=config.logging.file or None,
    )

    client = LLMClient(config.llm)

    # Quick health check before launching the REPL
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


__all__ = ["DEFAULT_SYSTEM_MESSAGE", "main_repl_loop", "run_repl"]
