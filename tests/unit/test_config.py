"""Tests for muru.utils.config."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from muru.utils.config import (
    Config,
    LLMConfig,
    LoggingConfig,
    PathsConfig,
    _apply_env_overrides,
    _deep_merge,
    _read_yaml,
    load_config,
)

# ============================================
# Fixtures
# ============================================


@pytest.fixture
def tmp_default_yaml(tmp_path: Path) -> Path:
    """Create a minimal valid default config in a temp directory."""
    path = tmp_path / "default.yaml"
    path.write_text(
        """
llm:
  fast: "test-fast"
  balanced: "test-balanced"
  deep: "test-deep"
  default_profile: "fast"
  host: "http://localhost:11434"
  timeout_seconds: 60
  temperature: 0.5
  max_retries: 2
logging:
  level: "INFO"
  format: "human"
  file: ""
paths:
  data_dir: "/tmp/muru-data"
  config_dir: "/tmp/muru-config"
"""
    )
    return path


@pytest.fixture
def empty_user_yaml(tmp_path: Path) -> Path:
    """Path to a non-existent user config (default case)."""
    return tmp_path / "nonexistent.yaml"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all MURU_* environment variables for test isolation."""
    for key in list(os.environ.keys()):
        if key.startswith("MURU_"):
            monkeypatch.delenv(key, raising=False)


# ============================================
# Schema validation tests
# ============================================


def test_default_llm_config_is_valid() -> None:
    """LLMConfig with no args should produce valid defaults."""
    config = LLMConfig()
    assert config.fast == "llama3.1:8b"
    assert config.deep == "deepseek-r1:70b"
    assert config.default_profile == "fast"
    assert config.timeout_seconds == 300


def test_llm_config_model_for_returns_correct_profile() -> None:
    """model_for() should return the correct model for each profile."""
    config = LLMConfig(
        fast="model-A",
        balanced="model-B",
        deep="model-C",
        default_profile="balanced",
    )
    assert config.model_for("fast") == "model-A"
    assert config.model_for("balanced") == "model-B"
    assert config.model_for("deep") == "model-C"


def test_llm_config_model_for_uses_default_when_none() -> None:
    """model_for(None) should use default_profile."""
    config = LLMConfig(
        fast="fast-m",
        balanced="balanced-m",
        deep="deep-m",
        default_profile="deep",
    )
    assert config.model_for(None) == "deep-m"
    assert config.model_for() == "deep-m"


def test_llm_config_rejects_invalid_default_profile() -> None:
    """default_profile must be one of fast/balanced/deep."""
    with pytest.raises(ValueError):
        LLMConfig(default_profile="ultra")  # type: ignore[arg-type]


def test_llm_config_rejects_negative_timeout() -> None:
    """LLM timeout must be positive."""
    with pytest.raises(ValueError):
        LLMConfig(timeout_seconds=-5)


def test_llm_config_rejects_excessive_temperature() -> None:
    """LLM temperature has an upper bound."""
    with pytest.raises(ValueError):
        LLMConfig(temperature=5.0)


def test_logging_config_normalizes_level_to_upper() -> None:
    """Log level is normalized to upper case."""
    config = LoggingConfig(level="debug")
    assert config.level == "DEBUG"


def test_logging_config_rejects_invalid_level() -> None:
    """Invalid log levels raise ValueError."""
    with pytest.raises(ValueError, match="Invalid log level"):
        LoggingConfig(level="LOUD")


def test_logging_config_normalizes_format_to_lower() -> None:
    """Log format is normalized to lower case."""
    config = LoggingConfig(format="JSON")
    assert config.format == "json"


def test_logging_config_rejects_invalid_format() -> None:
    """Invalid log formats raise ValueError."""
    with pytest.raises(ValueError, match="Invalid log format"):
        LoggingConfig(format="xml")


def test_paths_config_expands_tilde() -> None:
    """~ in paths is expanded to the user home directory."""
    config = PathsConfig(data_dir="~/foo", config_dir="~/bar")
    assert "~" not in config.data_dir
    assert "~" not in config.config_dir
    assert config.data_dir.endswith("/foo")
    assert config.config_dir.endswith("/bar")


# ============================================
# YAML reading tests
# ============================================


def test_read_yaml_returns_empty_dict_for_missing_file(tmp_path: Path) -> None:
    """Missing file → empty dict (not an error)."""
    result = _read_yaml(tmp_path / "nope.yaml")
    assert result == {}


def test_read_yaml_returns_empty_dict_for_empty_file(tmp_path: Path) -> None:
    """Empty file → empty dict."""
    path = tmp_path / "empty.yaml"
    path.touch()
    assert _read_yaml(path) == {}


def test_read_yaml_raises_on_malformed_yaml(tmp_path: Path) -> None:
    """Malformed YAML raises ValueError with helpful message."""
    path = tmp_path / "bad.yaml"
    path.write_text("not: valid: yaml: ::: :")
    with pytest.raises(ValueError, match="Failed to parse YAML"):
        _read_yaml(path)


def test_read_yaml_raises_on_non_dict_top_level(tmp_path: Path) -> None:
    """Top-level YAML must be a dict, not a list/string/etc."""
    path = tmp_path / "list.yaml"
    path.write_text("- one\n- two\n")
    with pytest.raises(ValueError, match="must be a mapping"):
        _read_yaml(path)


# ============================================
# Deep merge tests
# ============================================


def test_deep_merge_overrides_scalars() -> None:
    """Override scalars replace base scalars."""
    result = _deep_merge({"a": 1, "b": 2}, {"b": 99})
    assert result == {"a": 1, "b": 99}


def test_deep_merge_recurses_into_nested_dicts() -> None:
    """Nested dicts are merged key-by-key, not replaced wholesale."""
    base = {"llm": {"fast": "x", "deep": "y"}}
    override = {"llm": {"deep": "z"}}
    result = _deep_merge(base, override)
    assert result == {"llm": {"fast": "x", "deep": "z"}}


def test_deep_merge_does_not_mutate_inputs() -> None:
    """Inputs to _deep_merge should not be modified."""
    base: dict[str, Any] = {"x": {"a": 1}}
    override: dict[str, Any] = {"x": {"b": 2}}
    _deep_merge(base, override)
    assert base == {"x": {"a": 1}}
    assert override == {"x": {"b": 2}}


# ============================================
# Env override tests
# ============================================


def test_env_override_applies_to_known_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MURU_LLM_FAST should override config['llm']['fast']."""
    monkeypatch.setenv("MURU_LLM_FAST", "overridden-model")
    base = {"llm": {"fast": "default-model"}}
    result = _apply_env_overrides(base)
    assert result["llm"]["fast"] == "overridden-model"


def test_env_override_ignores_unknown_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Env vars for unknown sections are silently ignored."""
    monkeypatch.setenv("MURU_NONSENSE_FOO", "bar")
    base = {"llm": {"fast": "x"}}
    result = _apply_env_overrides(base)
    assert "nonsense" not in result


def test_env_override_does_not_mutate_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_apply_env_overrides should return a new dict, not mutate."""
    monkeypatch.setenv("MURU_LLM_FAST", "new")
    base = {"llm": {"fast": "old"}}
    _apply_env_overrides(base)
    assert base["llm"]["fast"] == "old"


# ============================================
# Full load_config integration tests
# ============================================


def test_load_config_with_defaults_only(tmp_default_yaml: Path, empty_user_yaml: Path) -> None:
    """Loading with no user file or env vars uses defaults."""
    config = load_config(
        default_path=tmp_default_yaml,
        user_path=empty_user_yaml,
        apply_env=False,
    )
    assert isinstance(config, Config)
    assert config.llm.fast == "test-fast"
    assert config.llm.deep == "test-deep"
    assert config.llm.timeout_seconds == 60


def test_load_config_user_overrides_defaults(tmp_default_yaml: Path, tmp_path: Path) -> None:
    """User config layers on top of defaults."""
    user_path = tmp_path / "user.yaml"
    user_path.write_text("llm:\n  fast: 'user-fast'\n")

    config = load_config(
        default_path=tmp_default_yaml,
        user_path=user_path,
        apply_env=False,
    )
    # User overrides fast model
    assert config.llm.fast == "user-fast"
    # But other LLM settings come from default
    assert config.llm.deep == "test-deep"
    assert config.llm.timeout_seconds == 60


def test_load_config_env_overrides_user_and_default(
    tmp_default_yaml: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Env vars beat both user file and defaults."""
    user_path = tmp_path / "user.yaml"
    user_path.write_text("llm:\n  fast: 'user-fast'\n")
    monkeypatch.setenv("MURU_LLM_FAST", "env-fast")

    config = load_config(
        default_path=tmp_default_yaml,
        user_path=user_path,
        apply_env=True,
    )
    assert config.llm.fast == "env-fast"


def test_load_config_raises_if_default_missing(tmp_path: Path) -> None:
    """Missing default config is a fatal error."""
    with pytest.raises(FileNotFoundError, match="Default config not found"):
        load_config(default_path=tmp_path / "nonexistent.yaml")


def test_load_config_validates_values(tmp_path: Path) -> None:
    """Bad values in YAML cause Pydantic validation errors."""
    path = tmp_path / "bad.yaml"
    path.write_text("llm:\n  temperature: 99.9\n")  # Above max
    with pytest.raises(ValueError):
        load_config(default_path=path, apply_env=False)
