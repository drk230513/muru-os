"""Tests for muru.ui.cli.repl."""

from __future__ import annotations

import io
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from muru.llm.exceptions import LLMConnectionError
from muru.ui.cli.repl import run_repl


@pytest.fixture
def mock_client() -> MagicMock:
    """A MagicMock pretending to be an LLMClient."""
    client = MagicMock()
    client._resolve_model.return_value = "test-model"
    return client


@pytest.fixture
def captured_console() -> Console:
    """A Rich Console that writes to a string buffer instead of stdout.

    Use console.file.getvalue() to inspect output.
    """
    buf = io.StringIO()
    return Console(file=buf, width=80, force_terminal=False, color_system=None)


def _scripted_input(*responses: str) -> MagicMock:
    """Build a MagicMock that returns successive strings on each call."""
    mock = MagicMock()
    mock.side_effect = list(responses)
    return mock


def test_repl_prints_welcome_banner(
    mock_client: MagicMock, captured_console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The welcome banner should appear on startup."""
    monkeypatch.setattr(captured_console, "input", _scripted_input("exit"))
    run_repl(mock_client, console=captured_console)
    output = captured_console.file.getvalue()  # type: ignore[attr-defined]

    assert "Muru" in output
    assert "v0.1.0" in output
    assert "test-model" in output


def test_repl_exits_on_exit_command(
    mock_client: MagicMock, captured_console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Typing 'exit' should terminate the loop without calling the LLM."""
    monkeypatch.setattr(captured_console, "input", _scripted_input("exit"))
    run_repl(mock_client, console=captured_console)

    mock_client.chat.assert_not_called()


def test_repl_exits_on_quit_command(
    mock_client: MagicMock, captured_console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Typing 'quit' should also terminate."""
    monkeypatch.setattr(captured_console, "input", _scripted_input("quit"))
    run_repl(mock_client, console=captured_console)

    mock_client.chat.assert_not_called()


def test_repl_help_command_does_not_call_llm(
    mock_client: MagicMock, captured_console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Typing 'help' should print help and not send to LLM."""
    monkeypatch.setattr(captured_console, "input", _scripted_input("help", "exit"))
    run_repl(mock_client, console=captured_console)

    mock_client.chat.assert_not_called()
    output = captured_console.file.getvalue()  # type: ignore[attr-defined]
    assert "Commands" in output


def test_repl_sends_user_input_to_llm(
    mock_client: MagicMock, captured_console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    """User input should be added to history and sent to LLM."""
    mock_client.chat.return_value = "Hello back!"
    monkeypatch.setattr(captured_console, "input", _scripted_input("hi there", "exit"))
    run_repl(mock_client, console=captured_console)

    assert mock_client.chat.called
    sent_messages = mock_client.chat.call_args[0][0]
    # Should include system message + user's input
    user_messages = [m for m in sent_messages if m["role"] == "user"]
    assert len(user_messages) == 1
    assert user_messages[0]["content"] == "hi there"


def test_repl_includes_system_message_by_default(
    mock_client: MagicMock, captured_console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default system message should be the first message sent."""
    mock_client.chat.return_value = "ok"
    monkeypatch.setattr(captured_console, "input", _scripted_input("hi", "exit"))
    run_repl(mock_client, console=captured_console)

    sent_messages = mock_client.chat.call_args[0][0]
    assert sent_messages[0]["role"] == "system"
    assert "Muru" in sent_messages[0]["content"]


def test_repl_uses_custom_system_message(
    mock_client: MagicMock, captured_console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A custom system_message should override the default."""
    mock_client.chat.return_value = "ok"
    monkeypatch.setattr(captured_console, "input", _scripted_input("hi", "exit"))
    run_repl(
        mock_client,
        system_message="You are a pirate.",
        console=captured_console,
    )

    sent_messages = mock_client.chat.call_args[0][0]
    assert sent_messages[0]["content"] == "You are a pirate."


def test_repl_keeps_history_across_turns(
    mock_client: MagicMock, captured_console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Second turn should include both turns in the history sent to LLM."""
    mock_client.chat.side_effect = ["First reply", "Second reply"]
    monkeypatch.setattr(
        captured_console,
        "input",
        _scripted_input("first message", "second message", "exit"),
    )
    run_repl(mock_client, console=captured_console)

    # Inspect the second LLM call's history
    second_call_messages = mock_client.chat.call_args_list[1][0][0]
    user_messages = [m for m in second_call_messages if m["role"] == "user"]
    assert len(user_messages) == 2
    assert user_messages[0]["content"] == "first message"
    assert user_messages[1]["content"] == "second message"


def test_repl_rolls_back_user_message_on_llm_error(
    mock_client: MagicMock, captured_console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the LLM errors, the failed user message must not pollute history."""
    # First call fails, second succeeds
    mock_client.chat.side_effect = [
        LLMConnectionError("boom"),
        "actual reply",
    ]
    monkeypatch.setattr(
        captured_console,
        "input",
        _scripted_input("failing message", "successful message", "exit"),
    )
    run_repl(mock_client, console=captured_console)

    # Second call's history should NOT contain the failing message
    second_call_messages = mock_client.chat.call_args_list[1][0][0]
    user_messages = [m for m in second_call_messages if m["role"] == "user"]
    assert len(user_messages) == 1
    assert user_messages[0]["content"] == "successful message"


def test_repl_handles_empty_input_gracefully(
    mock_client: MagicMock, captured_console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty input should not call the LLM and should re-prompt."""
    monkeypatch.setattr(captured_console, "input", _scripted_input("", "  ", "exit"))
    run_repl(mock_client, console=captured_console)

    mock_client.chat.assert_not_called()
