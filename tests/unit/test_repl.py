"""Tests for muru.ui.cli.repl.

In v0.2.0+, the REPL routes through the Orchestrator. We mock the
orchestrator (and the LLMClient stops being directly relevant) so the
tests don't need a real LLM or registry.
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from muru.orchestrator.result import OrchestratorResult
from muru.planner.plan import Plan
from muru.ui.cli.repl import run_repl


@pytest.fixture
def mock_client() -> MagicMock:
    """A MagicMock pretending to be an LLMClient."""
    client = MagicMock()
    client._resolve_model.return_value = "test-model"
    return client


@pytest.fixture
def captured_console() -> Console:
    """A Rich Console that writes to a string buffer instead of stdout."""
    buf = io.StringIO()
    return Console(file=buf, width=80, force_terminal=False, color_system=None)


def _scripted_input(*responses: str) -> MagicMock:
    """Build a MagicMock that returns successive strings on each call."""
    mock = MagicMock()
    mock.side_effect = list(responses)
    return mock


def _make_response_result(intent: str, response: str) -> OrchestratorResult:
    """Build a conversational OrchestratorResult."""
    return OrchestratorResult(
        intent=intent,
        plan=Plan(needs_tool=False, response=response),
        final_response=response,
    )


def test_repl_prints_welcome_banner(
    mock_client: MagicMock,
    captured_console: Console,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The welcome banner should appear on startup."""
    monkeypatch.setattr(captured_console, "input", _scripted_input("exit"))
    run_repl(mock_client, console=captured_console)
    output = captured_console.file.getvalue()  # type: ignore[attr-defined]

    assert "Muru" in output
    assert "v0.2.0" in output
    assert "test-model" in output


def test_repl_exits_on_exit_command(
    mock_client: MagicMock,
    captured_console: Console,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Typing 'exit' should terminate the loop without invoking orchestrator."""
    monkeypatch.setattr(captured_console, "input", _scripted_input("exit"))

    with patch("muru.ui.cli.repl.Orchestrator") as MockOrchestrator:
        run_repl(mock_client, console=captured_console)

    MockOrchestrator.return_value.handle.assert_not_called()


def test_repl_exits_on_quit_command(
    mock_client: MagicMock,
    captured_console: Console,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Typing 'quit' should also terminate."""
    monkeypatch.setattr(captured_console, "input", _scripted_input("quit"))

    with patch("muru.ui.cli.repl.Orchestrator") as MockOrchestrator:
        run_repl(mock_client, console=captured_console)

    MockOrchestrator.return_value.handle.assert_not_called()


def test_repl_help_command_does_not_call_orchestrator(
    mock_client: MagicMock,
    captured_console: Console,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Typing 'help' should print help and not invoke orchestrator."""
    monkeypatch.setattr(captured_console, "input", _scripted_input("help", "exit"))
    with patch("muru.ui.cli.repl.Orchestrator") as MockOrchestrator:
        run_repl(mock_client, console=captured_console)

    MockOrchestrator.return_value.handle.assert_not_called()
    output = captured_console.file.getvalue()  # type: ignore[attr-defined]
    assert "Commands" in output


def test_repl_calls_orchestrator_with_user_input(
    mock_client: MagicMock,
    captured_console: Console,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User input should be passed to orchestrator.handle()."""
    monkeypatch.setattr(captured_console, "input", _scripted_input("hi there", "exit"))

    with patch("muru.ui.cli.repl.Orchestrator") as MockOrchestrator:
        mock_orch_instance = MockOrchestrator.return_value
        mock_orch_instance.handle.return_value = _make_response_result("hi there", "Hello!")
        run_repl(mock_client, console=captured_console)

    mock_orch_instance.handle.assert_called_once_with("hi there")


def test_repl_renders_final_response(
    mock_client: MagicMock,
    captured_console: Console,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The orchestrator's final_response should appear in the output."""
    monkeypatch.setattr(captured_console, "input", _scripted_input("hello", "exit"))

    with patch("muru.ui.cli.repl.Orchestrator") as MockOrchestrator:
        MockOrchestrator.return_value.handle.return_value = _make_response_result(
            "hello", "Hi there friend"
        )
        run_repl(mock_client, console=captured_console)

    output = captured_console.file.getvalue()  # type: ignore[attr-defined]
    assert "Hi there friend" in output


def test_repl_handles_empty_input_gracefully(
    mock_client: MagicMock,
    captured_console: Console,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty input should not call orchestrator and should re-prompt."""
    monkeypatch.setattr(captured_console, "input", _scripted_input("", "  ", "exit"))
    with patch("muru.ui.cli.repl.Orchestrator") as MockOrchestrator:
        run_repl(mock_client, console=captured_console)

    MockOrchestrator.return_value.handle.assert_not_called()


def test_repl_renders_error_when_orchestrator_returns_one(
    mock_client: MagicMock,
    captured_console: Console,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When orchestrator returns an error, REPL shows it (with the friendly message)."""
    monkeypatch.setattr(captured_console, "input", _scripted_input("bad input", "exit"))

    with patch("muru.ui.cli.repl.Orchestrator") as MockOrchestrator:
        MockOrchestrator.return_value.handle.return_value = OrchestratorResult(
            intent="bad input",
            final_response="I couldn't figure that out.",
            error="PlannerError: nope",
        )
        run_repl(mock_client, console=captured_console)

    output = captured_console.file.getvalue()  # type: ignore[attr-defined]
    assert "I couldn't figure that out" in output
    # The technical error appears in dim red below
    assert "PlannerError" in output


def test_repl_survives_orchestrator_unexpected_exception(
    mock_client: MagicMock,
    captured_console: Console,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If orchestrator raises (it shouldn't), REPL catches and continues."""
    monkeypatch.setattr(
        captured_console,
        "input",
        _scripted_input("bad", "second", "exit"),
    )

    with patch("muru.ui.cli.repl.Orchestrator") as MockOrchestrator:
        # First call raises; second call succeeds
        MockOrchestrator.return_value.handle.side_effect = [
            RuntimeError("boom"),
            _make_response_result("second", "ok now"),
        ]
        run_repl(mock_client, console=captured_console)

    output = captured_console.file.getvalue()  # type: ignore[attr-defined]
    assert "Unexpected error" in output
    assert "ok now" in output
