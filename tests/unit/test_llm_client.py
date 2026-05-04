"""Tests for muru.llm.client.

Most tests use a mocked Ollama client to test logic without needing
a real Ollama server. One integration test (marked with @pytest.mark.integration)
talks to a real Ollama and is skipped by default.

To run only fast unit tests:    pytest
To run integration tests too:   pytest -m integration
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from muru.llm.client import LLMClient
from muru.llm.exceptions import (
    LLMConnectionError,
    LLMResponseError,
    ModelNotFoundError,
)
from muru.utils.config import LLMConfig

# ============================================
# Fixtures
# ============================================


@pytest.fixture
def llm_config() -> LLMConfig:
    """A standard LLMConfig for testing."""
    return LLMConfig(
        fast="test-fast-model",
        balanced="test-balanced-model",
        deep="test-deep-model",
        default_profile="fast",
        host="http://localhost:11434",
        timeout_seconds=10,
        temperature=0.0,
        max_retries=2,
    )


@pytest.fixture
def mock_ollama_response() -> dict[str, Any]:
    """A mock Ollama chat response."""
    return {
        "model": "test-fast-model",
        "message": {"role": "assistant", "content": "Hello world"},
        "done": True,
    }


@pytest.fixture
def mock_ollama_list_response() -> dict[str, Any]:
    """A mock Ollama list response with our test models."""
    return {
        "models": [
            {"model": "test-fast-model"},
            {"model": "test-balanced-model"},
            {"model": "test-deep-model"},
        ]
    }


# ============================================
# Construction & basic state
# ============================================


def test_client_initializes_with_config(llm_config: LLMConfig) -> None:
    """Client should construct cleanly from a valid LLMConfig."""
    with patch("muru.llm.client.ollama.Client"):
        client = LLMClient(llm_config)
        assert client._config is llm_config
        assert client._available_models == set()


def test_resolve_model_uses_default_when_no_profile(
    llm_config: LLMConfig,
) -> None:
    """When profile is None, _resolve_model returns default_profile's model."""
    with patch("muru.llm.client.ollama.Client"):
        client = LLMClient(llm_config)
        assert client._resolve_model(None) == "test-fast-model"


def test_resolve_model_respects_explicit_profile(llm_config: LLMConfig) -> None:
    """Passing a profile name should look up that profile's model."""
    with patch("muru.llm.client.ollama.Client"):
        client = LLMClient(llm_config)
        assert client._resolve_model("deep") == "test-deep-model"
        assert client._resolve_model("balanced") == "test-balanced-model"


# ============================================
# Availability check
# ============================================


def test_is_available_returns_true_when_ollama_responds(
    llm_config: LLMConfig,
) -> None:
    """is_available() should return True when ollama.list() succeeds."""
    with patch("muru.llm.client.ollama.Client") as MockClient:
        MockClient.return_value.list.return_value = {"models": []}
        client = LLMClient(llm_config)
        assert client.is_available() is True


def test_is_available_returns_false_when_ollama_errors(
    llm_config: LLMConfig,
) -> None:
    """is_available() should return False when ollama.list() raises."""
    with patch("muru.llm.client.ollama.Client") as MockClient:
        MockClient.return_value.list.side_effect = ConnectionRefusedError("nope")
        client = LLMClient(llm_config)
        assert client.is_available() is False


# ============================================
# Model availability check
# ============================================


def test_ensure_model_available_passes_for_known_model(
    llm_config: LLMConfig, mock_ollama_list_response: dict[str, Any]
) -> None:
    """ensure_model_available() should not raise for a known model."""
    with patch("muru.llm.client.ollama.Client") as MockClient:
        MockClient.return_value.list.return_value = mock_ollama_list_response
        client = LLMClient(llm_config)
        client.ensure_model_available("test-fast-model")  # Should not raise


def test_ensure_model_available_raises_for_unknown_model(
    llm_config: LLMConfig, mock_ollama_list_response: dict[str, Any]
) -> None:
    """ensure_model_available() should raise ModelNotFoundError for unknown models."""
    with patch("muru.llm.client.ollama.Client") as MockClient:
        MockClient.return_value.list.return_value = mock_ollama_list_response
        client = LLMClient(llm_config)
        with pytest.raises(ModelNotFoundError, match="not available in Ollama"):
            client.ensure_model_available("nonexistent-model")


def test_ensure_model_available_raises_on_connection_failure(
    llm_config: LLMConfig,
) -> None:
    """Connection failure during ensure_model_available raises LLMConnectionError."""
    with patch("muru.llm.client.ollama.Client") as MockClient:
        MockClient.return_value.list.side_effect = ConnectionRefusedError()
        client = LLMClient(llm_config)
        with pytest.raises(LLMConnectionError, match="Could not reach Ollama"):
            client.ensure_model_available("any-model")


def test_ensure_model_available_caches_results(
    llm_config: LLMConfig, mock_ollama_list_response: dict[str, Any]
) -> None:
    """Subsequent checks for the same model don't re-call Ollama."""
    with patch("muru.llm.client.ollama.Client") as MockClient:
        MockClient.return_value.list.return_value = mock_ollama_list_response
        client = LLMClient(llm_config)
        client.ensure_model_available("test-fast-model")
        client.ensure_model_available("test-fast-model")
        client.ensure_model_available("test-fast-model")
        # Should have been called only once (the first check)
        assert MockClient.return_value.list.call_count == 1


# ============================================
# Chat / Complete functionality
# ============================================


def test_complete_returns_assistant_text(
    llm_config: LLMConfig,
    mock_ollama_response: dict[str, Any],
    mock_ollama_list_response: dict[str, Any],
) -> None:
    """complete() should return the assistant's content as a string."""
    with patch("muru.llm.client.ollama.Client") as MockClient:
        MockClient.return_value.list.return_value = mock_ollama_list_response
        MockClient.return_value.chat.return_value = mock_ollama_response

        client = LLMClient(llm_config)
        result = client.complete("Hello?")

        assert result == "Hello world"


def test_complete_passes_system_message_when_provided(
    llm_config: LLMConfig,
    mock_ollama_response: dict[str, Any],
    mock_ollama_list_response: dict[str, Any],
) -> None:
    """complete(system=...) should prepend a system message."""
    with patch("muru.llm.client.ollama.Client") as MockClient:
        MockClient.return_value.list.return_value = mock_ollama_list_response
        MockClient.return_value.chat.return_value = mock_ollama_response

        client = LLMClient(llm_config)
        client.complete("Hi", system="You are concise.")

        call_args = MockClient.return_value.chat.call_args
        messages = call_args.kwargs["messages"]
        assert len(messages) == 2
        assert messages[0] == {"role": "system", "content": "You are concise."}
        assert messages[1] == {"role": "user", "content": "Hi"}


def test_complete_uses_specified_profile(
    llm_config: LLMConfig,
    mock_ollama_response: dict[str, Any],
    mock_ollama_list_response: dict[str, Any],
) -> None:
    """complete(profile='deep') should call Ollama with the deep model."""
    with patch("muru.llm.client.ollama.Client") as MockClient:
        MockClient.return_value.list.return_value = mock_ollama_list_response
        MockClient.return_value.chat.return_value = mock_ollama_response

        client = LLMClient(llm_config)
        client.complete("Hi", profile="deep")

        call_args = MockClient.return_value.chat.call_args
        assert call_args.kwargs["model"] == "test-deep-model"


def test_chat_raises_on_malformed_response(
    llm_config: LLMConfig,
    mock_ollama_list_response: dict[str, Any],
) -> None:
    """A response missing 'message' should raise LLMResponseError."""
    with patch("muru.llm.client.ollama.Client") as MockClient:
        MockClient.return_value.list.return_value = mock_ollama_list_response
        MockClient.return_value.chat.return_value = {"unexpected": "shape"}

        client = LLMClient(llm_config)
        with pytest.raises(LLMResponseError, match="Could not parse"):
            client.complete("Hi")


# ============================================
# Integration test (real Ollama)
# ============================================


@pytest.mark.integration
def test_real_ollama_responds() -> None:
    """End-to-end test against a real local Ollama. Skipped by default.

    Run with: pytest -m integration
    """
    from muru.utils.config import load_config

    config = load_config()
    client = LLMClient(config.llm)

    if not client.is_available():
        pytest.skip("Ollama not running on localhost — skipping integration test")

    response = client.complete("Reply with exactly: OK")
    assert isinstance(response, str)
    assert len(response) > 0
