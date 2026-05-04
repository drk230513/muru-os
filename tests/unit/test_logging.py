"""Tests for muru.utils.logging."""

from __future__ import annotations

import json

import pytest

from muru.utils.logging import (
    configure_logging,
    get_logger,
    reset_for_testing,
)


@pytest.fixture(autouse=True)
def reset_logging_between_tests() -> None:
    """Reset logging config before each test for isolation.

    The autouse=True flag means this fixture runs automatically for every
    test in this file, no need to request it explicitly.
    """
    reset_for_testing()


def test_get_logger_returns_a_logger() -> None:
    """get_logger() returns something we can log with."""
    log = get_logger("muru.test")
    assert log is not None
    # Should have the standard log methods
    assert hasattr(log, "info")
    assert hasattr(log, "warning")
    assert hasattr(log, "error")
    assert hasattr(log, "debug")


def test_get_logger_auto_configures() -> None:
    """Calling get_logger() before configure_logging() should still work.

    This is a usability feature: scripts and tests shouldn't have to
    remember to configure logging before using it.
    """
    # No configure_logging() call — get_logger should self-bootstrap
    log = get_logger("muru.test")
    log.info("test_event", key="value")
    # If we got here without exception, the auto-config worked


def test_configure_logging_with_valid_level() -> None:
    """All standard log levels should be accepted."""
    for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
        reset_for_testing()
        configure_logging(level=level)
        # If we get here, no exception was raised


def test_configure_logging_is_case_insensitive() -> None:
    """Lowercase level names should also work."""
    configure_logging(level="info")
    reset_for_testing()
    configure_logging(level="DeBuG")


def test_configure_logging_rejects_invalid_level() -> None:
    """Bogus level names should raise ValueError with a helpful message."""
    with pytest.raises(ValueError, match="Invalid log level"):
        configure_logging(level="LOUD")


def test_configure_logging_is_idempotent() -> None:
    """Calling configure_logging twice shouldn't error or reconfigure."""
    configure_logging(level="INFO")
    configure_logging(level="DEBUG")  # Second call is silently ignored
    # No exception means success


def test_json_output_produces_valid_json(capsys: pytest.CaptureFixture[str]) -> None:
    """json_output=True should emit parseable JSON."""
    configure_logging(level="INFO", json_output=True)
    log = get_logger("muru.test")
    log.info("test_event", user="alice", count=42)

    captured = capsys.readouterr()
    output = captured.out.strip()

    # Should be a single line of valid JSON
    parsed = json.loads(output)

    # Should contain the event and our custom keys
    assert parsed["event"] == "test_event"
    assert parsed["user"] == "alice"
    assert parsed["count"] == 42
    assert parsed["level"] == "info"
    assert "timestamp" in parsed


def test_human_output_is_not_json(capsys: pytest.CaptureFixture[str]) -> None:
    """json_output=False should emit human-readable text (not JSON)."""
    configure_logging(level="INFO", json_output=False)
    log = get_logger("muru.test")
    log.info("test_event", key="value")

    captured = capsys.readouterr()
    output = captured.out.strip()

    # Should NOT be parseable as JSON (it's colorized human text)
    with pytest.raises(json.JSONDecodeError):
        json.loads(output)

    # But should still contain our event name and key
    assert "test_event" in output
    assert "key" in output
    assert "value" in output


def test_logger_name_appears_in_output(capsys: pytest.CaptureFixture[str]) -> None:
    """The logger's name should appear in the output for traceability."""
    configure_logging(level="INFO", json_output=True)
    log = get_logger("muru.specific.module")
    log.info("test_event")

    captured = capsys.readouterr()
    parsed = json.loads(captured.out.strip())

    assert parsed["logger"] == "muru.specific.module"


def test_reset_for_testing_allows_reconfiguration() -> None:
    """reset_for_testing() should let us reconfigure with new settings."""
    configure_logging(level="INFO")
    reset_for_testing()
    configure_logging(level="DEBUG")  # Would be silently ignored without reset
    # If no exception, reset worked
