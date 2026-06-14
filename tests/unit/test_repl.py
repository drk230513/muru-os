"""Tests for muru.ui.cli.repl.

In v0.3.0 the REPL constructs a CliConfirmationProvider, threads it
into the Orchestrator, and accumulates conversation history.
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel
from rich.console import Console

from muru.orchestrator.result import OrchestratorResult
from muru.planner.plan import Plan
from muru.ui.cli.repl import run_repl


@pytest.fixture
def mock_client() -> MagicMock:
    client = MagicMock()
    client._resolve_model.return_value = "test-model"
    return client


@pytest.fixture
def captured_console() -> Console:
    buf = io.StringIO()
    return Console(file=buf, width=80, force_terminal=False, color_system=None)


def _scripted_input(*responses: str) -> MagicMock:
    mock = MagicMock()
    mock.side_effect = list(responses)
    return mock


def _make_response_result(intent: str, response: str) -> OrchestratorResult:
    return OrchestratorResult(
        intent=intent,
        plan=Plan(needs_tool=False, response=response),
        final_response=response,
    )


# ----- Welcome / version -----


def test_repl_prints_welcome_banner_with_current_version(
    mock_client: MagicMock,
    captured_console: Console,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(captured_console, "input", _scripted_input("exit"))
    run_repl(mock_client, console=captured_console)
    output = captured_console.file.getvalue()  # type: ignore[attr-defined]

    assert "Muru" in output
    assert "v0.4.0" in output
    assert "test-model" in output


# ----- Built-in commands -----


def test_repl_exits_on_exit_command(
    mock_client: MagicMock,
    captured_console: Console,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(captured_console, "input", _scripted_input("exit"))

    with patch("muru.ui.cli.repl.Orchestrator") as MockOrchestrator:
        run_repl(mock_client, console=captured_console)

    MockOrchestrator.return_value.handle.assert_not_called()


def test_repl_exits_on_quit_command(
    mock_client: MagicMock,
    captured_console: Console,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(captured_console, "input", _scripted_input("quit"))

    with patch("muru.ui.cli.repl.Orchestrator") as MockOrchestrator:
        run_repl(mock_client, console=captured_console)

    MockOrchestrator.return_value.handle.assert_not_called()


def test_repl_help_command_does_not_call_orchestrator(
    mock_client: MagicMock,
    captured_console: Console,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(captured_console, "input", _scripted_input("help", "exit"))
    with patch("muru.ui.cli.repl.Orchestrator") as MockOrchestrator:
        run_repl(mock_client, console=captured_console)

    MockOrchestrator.return_value.handle.assert_not_called()
    output = captured_console.file.getvalue()  # type: ignore[attr-defined]
    assert "Commands" in output


def test_repl_clear_command_resets_history(
    mock_client: MagicMock,
    captured_console: Console,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After 'clear', history sent to orchestrator should be empty."""
    monkeypatch.setattr(
        captured_console,
        "input",
        _scripted_input("first", "clear", "second", "exit"),
    )

    with patch("muru.ui.cli.repl.Orchestrator") as MockOrchestrator:
        mock_orch = MockOrchestrator.return_value
        mock_orch.handle.side_effect = [
            _make_response_result("first", "reply 1"),
            _make_response_result("second", "reply 2"),
        ]
        run_repl(mock_client, console=captured_console)

    # First call: empty history
    first_kwargs = mock_orch.handle.call_args_list[0].kwargs
    assert first_kwargs.get("history") == []
    # After 'clear', second call should also have empty history
    # (since the user typed 'clear' BEFORE 'second')
    second_kwargs = mock_orch.handle.call_args_list[1].kwargs
    assert second_kwargs.get("history") == []


# ----- Orchestrator integration -----


def test_repl_calls_orchestrator_with_user_input(
    mock_client: MagicMock,
    captured_console: Console,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(captured_console, "input", _scripted_input("hi there", "exit"))

    with patch("muru.ui.cli.repl.Orchestrator") as MockOrchestrator:
        mock_orch_instance = MockOrchestrator.return_value
        mock_orch_instance.handle.return_value = _make_response_result("hi there", "Hello!")
        run_repl(mock_client, console=captured_console)

    # First positional arg should be the user input
    first_call = mock_orch_instance.handle.call_args_list[0]
    assert first_call.args[0] == "hi there"


def test_repl_renders_final_response(
    mock_client: MagicMock,
    captured_console: Console,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    monkeypatch.setattr(captured_console, "input", _scripted_input("", "  ", "exit"))
    with patch("muru.ui.cli.repl.Orchestrator") as MockOrchestrator:
        run_repl(mock_client, console=captured_console)

    MockOrchestrator.return_value.handle.assert_not_called()


def test_repl_renders_error_when_orchestrator_returns_one(
    mock_client: MagicMock,
    captured_console: Console,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    assert "PlannerError" in output


def test_repl_survives_orchestrator_unexpected_exception(
    mock_client: MagicMock,
    captured_console: Console,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        captured_console,
        "input",
        _scripted_input("bad", "second", "exit"),
    )

    with patch("muru.ui.cli.repl.Orchestrator") as MockOrchestrator:
        MockOrchestrator.return_value.handle.side_effect = [
            RuntimeError("boom"),
            _make_response_result("second", "ok now"),
        ]
        run_repl(mock_client, console=captured_console)

    output = captured_console.file.getvalue()  # type: ignore[attr-defined]
    assert "Unexpected error" in output
    assert "ok now" in output


# ----- History accumulation (v0.3.0) -----


def test_repl_accumulates_history_across_successful_turns(
    mock_client: MagicMock,
    captured_console: Console,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Second call to orchestrator.handle should see history from the first turn."""
    monkeypatch.setattr(
        captured_console,
        "input",
        _scripted_input("first message", "second message", "exit"),
    )

    with patch("muru.ui.cli.repl.Orchestrator") as MockOrchestrator:
        mock_orch = MockOrchestrator.return_value
        mock_orch.handle.side_effect = [
            _make_response_result("first message", "first reply"),
            _make_response_result("second message", "second reply"),
        ]
        run_repl(mock_client, console=captured_console)

    # First call: empty history
    first_kwargs = mock_orch.handle.call_args_list[0].kwargs
    assert first_kwargs.get("history") == []
    # Second call: history contains first user + first assistant
    second_kwargs = mock_orch.handle.call_args_list[1].kwargs
    history = second_kwargs.get("history")
    assert history is not None
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "first message"
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == "first reply"


def test_repl_does_not_add_errored_turns_to_history(
    mock_client: MagicMock,
    captured_console: Console,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a turn returns an error, it should NOT be added to history."""
    monkeypatch.setattr(
        captured_console,
        "input",
        _scripted_input("bad", "good", "exit"),
    )

    with patch("muru.ui.cli.repl.Orchestrator") as MockOrchestrator:
        mock_orch = MockOrchestrator.return_value
        mock_orch.handle.side_effect = [
            OrchestratorResult(
                intent="bad",
                final_response="something broke",
                error="PlannerError: bad",
            ),
            _make_response_result("good", "ok"),
        ]
        run_repl(mock_client, console=captured_console)

    # Second turn's history should be empty (errored first turn not added)
    second_kwargs = mock_orch.handle.call_args_list[1].kwargs
    assert second_kwargs.get("history") == []


# ----- Confirmation provider construction -----


def test_repl_constructs_orchestrator_with_confirmation_provider(
    mock_client: MagicMock,
    captured_console: Console,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REPL must pass a CliConfirmationProvider to Orchestrator."""
    monkeypatch.setattr(captured_console, "input", _scripted_input("exit"))

    with patch("muru.ui.cli.repl.Orchestrator") as MockOrchestrator:
        run_repl(mock_client, console=captured_console)

    # Check the Orchestrator constructor got a confirmation_provider kwarg
    MockOrchestrator.assert_called_once()
    call_kwargs = MockOrchestrator.call_args.kwargs
    assert "confirmation_provider" in call_kwargs
    assert call_kwargs["confirmation_provider"] is not None


# ============================================
# Confirmation gating integration (v0.4.0)
# ============================================


def test_repl_does_not_invoke_tool_when_confirmation_provider_rejects(
    mock_client: MagicMock,
    captured_console: Console,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard: the REPL must NEVER silently bypass a Tier 2+ confirmation.

    Last session's spinner bug: console.status() monopolized the terminal,
    causing console.input() inside CliConfirmationProvider to return cached
    terminal content. The decision was logged as APPROVED, the tool ran,
    the file was overwritten - despite no visible prompt ever appearing.

    This test runs the REPL with a real CliConfirmationProvider, scripts
    the input to be 'no', and verifies that:
    - the tool was never invoked
    - the user-facing response indicates the action was declined

    If the spinner bug returns (or any future bug auto-approves Tier 2+
    without input), this test fails immediately.
    """
    from muru.policy.confirmation.cli import CliConfirmationProvider
    from muru.policy.risk import RiskTier
    from muru.tools.base import Tool, ToolResult

    # A fake Tier 3 tool the planner will "choose"
    class FakeArgs(BaseModel):
        pass

    class FakeResult(ToolResult):
        pass

    invoked_count = {"n": 0}

    def fake_impl(args: FakeArgs) -> FakeResult:
        invoked_count["n"] += 1
        return FakeResult(success=True, message="should never get here")

    fake_tool = Tool(
        name="fake_dangerous",
        description="A fake destructive tool used by integration tests.",
        args_model=FakeArgs,
        result_model=FakeResult,
        implementation=fake_impl,
        risk_tier=RiskTier.HIGH_RISK,
    )

    # Script: user submits a query, then confirmation prompts for 'yes',
    # then user types 'no' to reject, then exits
    monkeypatch.setattr(
        captured_console,
        "input",
        _scripted_input(
            "do the dangerous thing",  # user query
            "no",  # confirmation rejection
            "exit",  # exit command
        ),
    )

    # Build the full stack manually so we use a REAL provider
    # but a mocked planner that always picks the fake tool
    from muru.orchestrator.orchestrator import Orchestrator
    from muru.tools.registry import ToolRegistry

    local_registry = ToolRegistry()
    local_registry.register(fake_tool)

    mock_planner = MagicMock()
    mock_planner.plan.return_value = Plan(
        needs_tool=True,
        tool_name="fake_dangerous",
        tool_args={},
        reasoning="testing rejection path",
    )

    real_provider = CliConfirmationProvider(console=captured_console)
    orchestrator = Orchestrator(
        llm=mock_client,
        planner=mock_planner,
        registry=local_registry,
        confirmation_provider=real_provider,
    )

    with patch("muru.ui.cli.repl.Orchestrator", return_value=orchestrator):
        run_repl(mock_client, console=captured_console)

    # Critical assertion: the tool was NEVER invoked, because the user rejected
    assert invoked_count["n"] == 0, (
        f"Tool was invoked {invoked_count['n']} times despite user rejection - "
        "this means confirmation gating was bypassed. SECURITY BUG."
    )

    # Output should show the polite decline
    output = captured_console.file.getvalue()  # type: ignore[attr-defined]
    assert "will not" in output.lower() or "won't" in output.lower(), (
        f"REPL did not show a decline message. Output was:\n{output}"
    )


def test_repl_does_invoke_tool_when_confirmation_provider_approves(
    mock_client: MagicMock,
    captured_console: Console,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Companion to the rejection test: when the user types 'yes', the tool DOES run."""
    from muru.policy.confirmation.cli import CliConfirmationProvider
    from muru.policy.risk import RiskTier
    from muru.tools.base import Tool, ToolResult

    class FakeArgs(BaseModel):
        pass

    class FakeResult(ToolResult):
        pass

    invoked_count = {"n": 0}

    def fake_impl(args: FakeArgs) -> FakeResult:
        invoked_count["n"] += 1
        return FakeResult(success=True, message="ran ok")

    fake_tool = Tool(
        name="fake_dangerous",
        description="A fake destructive tool used by integration tests.",
        args_model=FakeArgs,
        result_model=FakeResult,
        implementation=fake_impl,
        risk_tier=RiskTier.HIGH_RISK,
    )

    # Mock the summarizer too, since the tool will actually run
    mock_client.chat.return_value = "Tool ran successfully"

    monkeypatch.setattr(
        captured_console,
        "input",
        _scripted_input(
            "do the dangerous thing",
            "yes",  # approval
            "exit",
        ),
    )

    from muru.orchestrator.orchestrator import Orchestrator
    from muru.tools.registry import ToolRegistry

    local_registry = ToolRegistry()
    local_registry.register(fake_tool)

    mock_planner = MagicMock()
    mock_planner.plan.return_value = Plan(
        needs_tool=True,
        tool_name="fake_dangerous",
        tool_args={},
        reasoning="testing approval path",
    )

    real_provider = CliConfirmationProvider(console=captured_console)
    orchestrator = Orchestrator(
        llm=mock_client,
        planner=mock_planner,
        registry=local_registry,
        confirmation_provider=real_provider,
    )

    with patch("muru.ui.cli.repl.Orchestrator", return_value=orchestrator):
        run_repl(mock_client, console=captured_console)

    assert invoked_count["n"] == 1, (
        f"Tool was invoked {invoked_count['n']} times, expected exactly 1 after user approval"
    )
