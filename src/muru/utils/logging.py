"""Structured logging for Muru.

This module configures structlog as the project-wide logging system. All
other Muru modules should import the `get_logger` function from here rather
than using the standard library's logging module directly.

Why structlog instead of stdlib logging?
    - Structured key=value events instead of string formatting
    - Easy switching between human-readable (development) and JSON (production)
    - Context propagation (add data once, it appears in every subsequent log)
    - Better performance than stdlib logging when used correctly

Usage:
    from muru.utils.logging import get_logger, configure_logging

    # In your application's entry point, configure once:
    configure_logging(level="INFO", json_output=False)

    # In any module, get a logger and use it:
    log = get_logger(__name__)
    log.info("user_request_received", intent="list files", source="cli")
    log.warning("tool_failed", tool="read_file", error="permission denied")
    log.error("planner_crashed", exc_info=True)

Output (human-readable mode):
    2026-05-04 12:30:00 [info     ] user_request_received  intent=list files source=cli

Output (JSON mode):
    {"timestamp": "2026-05-04T12:30:00Z", "level": "info", "event": "user_request_received", ...}
"""

from __future__ import annotations

import logging
import sys
from typing import cast

import structlog
from structlog.types import Processor

# Module-level flag: have we configured logging yet?
# Prevents double-configuration if configure_logging() is called multiple times.
_configured: bool = False


def configure_logging(
    level: str = "INFO",
    json_output: bool = False,
    log_file: str | None = None,
    force: bool = False,
) -> None:
    """Configure structlog and stdlib logging for the entire application.

    Call this once at the start of the application. Subsequent calls
    are no-ops unless force=True is passed (useful when an explicit config
    needs to override an earlier auto-configure from get_logger()).

    Args:
        level: Minimum log level to emit. One of: DEBUG, INFO, WARNING,
            ERROR, CRITICAL. Case-insensitive. Defaults to INFO.
        json_output: If True, emit JSON lines (good for production / audit
            log). If False, emit colorized human-readable output (good for
            development).
        log_file: Optional path to a file to additionally write logs to.
            If None, logs go only to stdout.
        force: If True, reconfigure even if logging has already been set up.
            Used by the main entry point to override the auto-configure that
            happens implicitly when get_logger() is called before any explicit
            configure_logging() call.

    Raises:
        ValueError: If `level` is not a valid log level name.
    """
    global _configured
    if _configured and not force:
        return

    # Validate level early with a clear error message
    level_upper = level.upper()
    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if level_upper not in valid_levels:
        raise ValueError(f"Invalid log level: {level!r}. Must be one of {sorted(valid_levels)}.")

    # Configure stdlib logging (structlog uses it under the hood)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file is not None:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        format="%(message)s",  # structlog handles formatting itself
        level=getattr(logging, level_upper),
        handlers=handlers,
        force=True,  # Override any prior config (e.g., from imported libs)
    )

    # Suppress noisy debug-level logs from third-party HTTP libraries.
    # These libraries log every HTTP request at INFO, which clutters our output.
    for noisy_logger in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    # Build the chain of structlog processors.
    # Each processor receives an event dict and returns a (possibly modified) one.
    # Order matters — they run top to bottom.
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,  # Merge context from contextvars
        structlog.stdlib.add_logger_name,  # Add logger name (e.g., "muru.llm")
        structlog.stdlib.add_log_level,  # Add level (info, error, etc.)
        structlog.processors.TimeStamper(fmt="iso", utc=True),  # ISO timestamp in UTC
        structlog.processors.StackInfoRenderer(),  # Add stack info if requested
        structlog.processors.format_exc_info,  # Format exception info
        structlog.processors.UnicodeDecoder(),  # Decode bytes to unicode
    ]

    # Final renderer differs by mode
    if json_output:
        renderer: Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level_upper)),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    _configured = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a configured structlog logger.

    Args:
        name: The logger name. By convention, pass `__name__` so the logger
            is named after its module (e.g., "muru.llm.client"). If None,
            the root logger is returned.

    Returns:
        A bound structlog logger ready to use.

    Example:
        >>> log = get_logger(__name__)
        >>> log.info("hello", user="alice")
    """
    # Auto-configure with sensible defaults if the user forgot to call
    # configure_logging(). This makes the library usable in tests and
    # quick scripts without ceremony.
    if not _configured:
        configure_logging()

    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))


def reset_for_testing() -> None:
    """Reset the logging configuration. Intended for use in test suites only.

    Without this, tests that call configure_logging() with different
    arguments would silently use whatever was configured first.
    """
    global _configured
    _configured = False
    structlog.reset_defaults()


__all__ = ["configure_logging", "get_logger", "reset_for_testing"]
