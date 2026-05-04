"""Custom exception classes for the LLM client.

Using specific exception types lets callers handle different failure
modes differently. For example, the orchestrator might retry on
LLMTimeoutError but give up immediately on ModelNotFoundError.
"""

from __future__ import annotations


class LLMError(Exception):
    """Base class for all LLM-related errors.

    Catch this if you want to handle any LLM failure generically.
    Catch a more specific subclass if you want to handle different
    failures differently.
    """


class ModelNotFoundError(LLMError):
    """The requested model is not available in Ollama.

    Typical fix: run `ollama pull <model_name>` to download it.
    """


class LLMConnectionError(LLMError):
    """Could not connect to the Ollama server.

    Typical cause: Ollama daemon is not running, or `host` setting
    in config points to the wrong address.
    """


class LLMTimeoutError(LLMError):
    """The LLM did not respond within the configured timeout.

    Typical cause: model is too large for hardware (swapping to disk),
    or prompt is too long. Try a smaller model or increase timeout.
    """


class LLMResponseError(LLMError):
    """The LLM returned a malformed or unexpected response.

    Typical cause: model crashed mid-generation, or response shape
    doesn't match what we expected. Retry usually helps.
    """


__all__ = [
    "LLMConnectionError",
    "LLMError",
    "LLMResponseError",
    "LLMTimeoutError",
    "ModelNotFoundError",
]
