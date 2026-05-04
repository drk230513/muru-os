"""LLM client for talking to Ollama.

This module wraps the `ollama` Python SDK with:
    - Configuration-driven model selection (uses muru.utils.config)
    - Structured logging of every request/response
    - Custom exceptions for specific failure modes
    - Automatic retry on transient errors
    - Health check (verify model is available before first use)

Usage:
    from muru.llm.client import LLMClient
    from muru.utils.config import load_config

    config = load_config()
    client = LLMClient(config.llm)

    # Quick completion (uses the default profile from config)
    response = client.complete("Say hello in one word.")
    print(response)

    # Specify a profile explicitly
    response = client.complete("Solve this hard problem", profile="deep")

    # Multi-turn chat
    messages = [
        {"role": "system", "content": "You are concise."},
        {"role": "user", "content": "What is the capital of France?"},
    ]
    response = client.chat(messages)
"""

from __future__ import annotations

import time
from typing import Any

import ollama
from ollama import ResponseError

from muru.llm.exceptions import (
    LLMConnectionError,
    LLMResponseError,
    LLMTimeoutError,
    ModelNotFoundError,
)
from muru.utils.config import LLMConfig, ModelProfile
from muru.utils.logging import get_logger

log = get_logger(__name__)


# Type alias for chat messages — list of dicts with role and content.
ChatMessage = dict[str, str]


class LLMClient:
    """Synchronous client for Ollama-hosted LLMs.

    Use one instance per application — it holds the underlying ollama
    Client and any cached model availability information.
    """

    def __init__(self, config: LLMConfig) -> None:
        """Construct an LLM client from configuration.

        Args:
            config: An LLMConfig instance (typically from load_config().llm).
        """
        self._config = config
        self._client = ollama.Client(host=config.host, timeout=config.timeout_seconds)
        # Cache of which models we've verified to be available.
        # Avoids repeated `ollama list` calls.
        self._available_models: set[str] = set()

        log.debug(
            "llm_client_initialized",
            host=config.host,
            default_profile=config.default_profile,
            timeout_seconds=config.timeout_seconds,
        )

    def _resolve_model(self, profile: ModelProfile | None) -> str:
        """Translate a profile name to the configured model tag."""
        return self._config.model_for(profile)

    def is_available(self) -> bool:
        """Check whether the Ollama server is reachable.

        Returns:
            True if Ollama responded, False otherwise.
        """
        try:
            self._client.list()
            return True
        except Exception as e:
            log.warning("ollama_unreachable", error=str(e), host=self._config.host)
            return False

    def ensure_model_available(self, model: str) -> None:
        """Verify a specific model is pulled in Ollama.

        Caches results so subsequent calls for the same model are free.

        Args:
            model: The Ollama model tag to check (e.g., 'llama3.1:8b').

        Raises:
            ModelNotFoundError: If the model is not in Ollama's local list.
            LLMConnectionError: If we couldn't reach Ollama at all.
        """
        if model in self._available_models:
            return

        try:
            response = self._client.list()
        except Exception as e:
            raise LLMConnectionError(f"Could not reach Ollama at {self._config.host}: {e}") from e

        # The Ollama list response has a 'models' key with a list of model objects.
        # Each model has a 'model' (or 'name') attribute. We accept both.
        model_names = set()
        for m in response.get("models", []):
            # Support both dict and object response formats across ollama versions
            name = m.get("model") if isinstance(m, dict) else getattr(m, "model", None)
            if name is None:
                name = m.get("name") if isinstance(m, dict) else getattr(m, "name", None)
            if name:
                model_names.add(name)

        if model not in model_names:
            raise ModelNotFoundError(
                f"Model {model!r} is not available in Ollama. "
                f"Available models: {sorted(model_names)}. "
                f"To install: `ollama pull {model}`"
            )

        self._available_models.add(model)
        log.debug("model_verified_available", model=model)

    def chat(
        self,
        messages: list[ChatMessage],
        profile: ModelProfile | None = None,
        temperature: float | None = None,
    ) -> str:
        """Send a multi-turn chat conversation and return the assistant's reply.

        Args:
            messages: List of {"role": ..., "content": ...} dicts.
                Roles can be "system", "user", or "assistant".
            profile: Which model profile to use (fast/balanced/deep).
                If None, uses the configured default_profile.
            temperature: Sampling temperature override. If None, uses config.

        Returns:
            The assistant's response text.

        Raises:
            ModelNotFoundError: If the resolved model isn't pulled in Ollama.
            LLMConnectionError: If Ollama is unreachable.
            LLMTimeoutError: If the request exceeds the configured timeout.
            LLMResponseError: If Ollama returns an unexpected response shape.
        """
        model = self._resolve_model(profile)
        temp = temperature if temperature is not None else self._config.temperature

        self.ensure_model_available(model)

        attempt = 0
        last_error: Exception | None = None

        while attempt <= self._config.max_retries:
            attempt += 1
            start = time.monotonic()
            log.info(
                "llm_request",
                model=model,
                profile=profile or self._config.default_profile,
                message_count=len(messages),
                attempt=attempt,
            )

            try:
                response = self._client.chat(
                    model=model,
                    messages=messages,
                    options={"temperature": temp},
                )
            except ResponseError as e:
                # Ollama reported an error — likely model issue or bad request
                last_error = e
                log.warning(
                    "llm_response_error",
                    error=str(e),
                    attempt=attempt,
                )
                if attempt > self._config.max_retries:
                    raise LLMResponseError(
                        f"Ollama returned error after {attempt} attempts: {e}"
                    ) from e
                # Exponential backoff before retry: 1s, 2s, 4s, ...
                time.sleep(2 ** (attempt - 1))
                continue
            except TimeoutError as e:
                raise LLMTimeoutError(
                    f"LLM request timed out after {self._config.timeout_seconds}s"
                ) from e
            except Exception as e:
                # Catch-all for unexpected SDK errors
                raise LLMConnectionError(f"Unexpected error talking to Ollama: {e}") from e

            elapsed = time.monotonic() - start

            # Extract the assistant's reply. Response shape:
            # {"message": {"role": "assistant", "content": "..."}, ...}
            try:
                content = self._extract_content(response)
            except (KeyError, TypeError, AttributeError) as e:
                raise LLMResponseError(
                    f"Could not parse Ollama response: {e}. Response: {response!r}"
                ) from e

            log.info(
                "llm_response",
                model=model,
                elapsed_seconds=round(elapsed, 2),
                response_chars=len(content),
            )
            return content

        # Loop exited without returning — should be impossible, but defensively:
        raise LLMResponseError(
            f"LLM request failed after {self._config.max_retries} retries"
        ) from last_error

    def complete(
        self,
        prompt: str,
        profile: ModelProfile | None = None,
        system: str | None = None,
        temperature: float | None = None,
    ) -> str:
        """Send a single-turn prompt and return the response.

        Convenience wrapper around chat() for the common case of a one-shot
        prompt with optional system message.

        Args:
            prompt: The user's prompt.
            profile: Which model profile to use.
            system: Optional system message to set context/persona.
            temperature: Sampling temperature override.

        Returns:
            The assistant's response text.
        """
        messages: list[ChatMessage] = []
        if system is not None:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages, profile=profile, temperature=temperature)

    @staticmethod
    def _extract_content(response: Any) -> str:
        """Pull the assistant's text from an Ollama chat response.

        Handles both dict-style and object-style responses across ollama versions.
        Raises KeyError if the response shape is invalid (e.g., missing 'message'
        or missing 'content' fields). The caller wraps this in LLMResponseError.
        """
        # Dict-style (older ollama versions)
        if isinstance(response, dict):
            if "message" not in response:
                raise KeyError("response has no 'message' field")
            message = response["message"]
            if isinstance(message, dict):
                if "content" not in message:
                    raise KeyError("message has no 'content' field")
                return str(message["content"])
            content = getattr(message, "content", None)
            if content is None:
                raise KeyError("message has no 'content' field")
            return str(content)

        # Object-style (newer ollama versions)
        message = getattr(response, "message", None)
        if message is None:
            raise KeyError("response has no 'message' field")
        content = getattr(message, "content", None)
        if content is None:
            if isinstance(message, dict):
                if "content" not in message:
                    raise KeyError("message has no 'content' field")
                content = message["content"]
            else:
                raise KeyError("message has no 'content' field")
        return str(content)


__all__ = ["ChatMessage", "LLMClient"]
