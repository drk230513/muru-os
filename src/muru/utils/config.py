"""Configuration loading and validation for Muru.

Loads configuration from three layers (later layers override earlier):

    1. Defaults shipped with the project (`config/default.yaml`)
    2. User overrides at `~/.config/muru/config.yaml` (optional)
    3. Environment variables prefixed `MURU_` (optional)

All config is validated through Pydantic models, so invalid values fail
fast with helpful error messages instead of mysteriously breaking later.

Usage:
    from muru.utils.config import load_config

    config = load_config()
    print(config.llm.fast)               # 'llama3.1:8b'
    print(config.llm.deep)               # 'deepseek-r1:70b'
    print(config.llm.default_profile)    # 'fast'
    print(config.llm.model_for("deep"))  # 'deepseek-r1:70b'
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal, cast

import yaml
from pydantic import BaseModel, Field, field_validator

from muru.utils.logging import get_logger

log = get_logger(__name__)


# ============================================
# Config schema (Pydantic models)
# ============================================


# Type alias for the valid profile names. Limits values at type-check time.
ModelProfile = Literal["fast", "balanced", "deep"]


class LLMConfig(BaseModel):
    """Settings for the language models.

    Muru supports three named "profiles" so calling code can request a
    model by *purpose* rather than by exact name:

        - fast     — quick, lightweight (tool selection, routing)
        - balanced — middle ground (most ordinary tasks)
        - deep     — heavyweight reasoning (complex planning, code analysis)

    All three profiles can map to the same actual model if you don't
    want to differentiate. The `default_profile` selects which is used
    when calling code doesn't specify one.
    """

    fast: str = Field(
        default="llama3.1:8b",
        description="Model for fast, low-latency tasks.",
    )
    balanced: str = Field(
        default="llama3.1:8b",
        description="Model for medium-complexity tasks.",
    )
    deep: str = Field(
        default="deepseek-r1:70b",
        description="Model for heavy reasoning tasks.",
    )
    default_profile: ModelProfile = Field(
        default="fast",
        description="Which profile to use when none is specified.",
    )

    host: str = Field(
        default="http://localhost:11434",
        description="Ollama server URL.",
    )
    timeout_seconds: int = Field(
        default=300,
        ge=1,
        le=3600,
        description="Max time to wait for a response, in seconds.",
    )
    temperature: float = Field(
        default=0.2,
        ge=0.0,
        le=2.0,
        description="Sampling temperature (0.0=deterministic, 2.0=very creative).",
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Max retry attempts on malformed responses.",
    )

    def model_for(self, profile: ModelProfile | None = None) -> str:
        """Return the Ollama model tag for the requested profile.

        Args:
            profile: Which profile to look up. If None, uses default_profile.

        Returns:
            The Ollama model tag (e.g., 'llama3.1:8b').
        """
        chosen = profile or self.default_profile
        return cast(str, getattr(self, chosen))


class LoggingConfig(BaseModel):
    """Settings for the logging system."""

    level: str = Field(default="INFO")
    format: str = Field(default="human")
    file: str = Field(default="")

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid:
            raise ValueError(f"Invalid log level: {v!r}. Must be one of {sorted(valid)}.")
        return upper

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        valid = {"human", "json"}
        lower = v.lower()
        if lower not in valid:
            raise ValueError(f"Invalid log format: {v!r}. Must be one of {sorted(valid)}.")
        return lower


class PathsConfig(BaseModel):
    """Settings for filesystem paths."""

    data_dir: str = Field(default="~/.local/share/muru")
    config_dir: str = Field(default="~/.config/muru")

    @field_validator("data_dir", "config_dir")
    @classmethod
    def expand_user(cls, v: str) -> str:
        """Expand ~ to the user's home directory."""
        return str(Path(v).expanduser())


class Config(BaseModel):
    """Top-level Muru configuration."""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)


# ============================================
# Loading and merging
# ============================================


def _read_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML file and return its contents as a dict."""
    if not path.exists():
        return {}

    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse YAML at {path}: {e}") from e

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(
            f"Top-level YAML at {path} must be a mapping (dict), got {type(data).__name__}"
        )
    return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge `override` into `base`. Override wins on conflict."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _apply_env_overrides(config_dict: dict[str, Any]) -> dict[str, Any]:
    """Apply environment variables to a config dict.

    Variables of the form MURU_<SECTION>_<KEY> override the corresponding
    section.key in the config.

    Examples:
        MURU_LLM_FAST=qwen2.5:14b              -> llm.fast
        MURU_LLM_DEFAULT_PROFILE=deep          -> llm.default_profile
        MURU_LOGGING_LEVEL=DEBUG               -> logging.level
    """
    result = {
        key: dict(value) if isinstance(value, dict) else value for key, value in config_dict.items()
    }

    for env_key, env_value in os.environ.items():
        if not env_key.startswith("MURU_"):
            continue

        remainder = env_key[len("MURU_") :]
        parts = remainder.split("_", 1)
        if len(parts) != 2:
            log.warning(
                "env_var_ignored",
                reason="expected MURU_SECTION_KEY format",
                var=env_key,
            )
            continue

        section, key = parts[0].lower(), parts[1].lower()

        if section not in result:
            log.warning(
                "env_var_ignored",
                reason="unknown config section",
                var=env_key,
                section=section,
            )
            continue
        if not isinstance(result[section], dict):
            continue

        result[section][key] = env_value
        log.debug("env_override_applied", section=section, key=key)

    return result


def load_config(
    default_path: Path | None = None,
    user_path: Path | None = None,
    apply_env: bool = True,
) -> Config:
    """Load and validate Muru configuration.

    Args:
        default_path: Path to the project default YAML.
        user_path: Path to user override YAML.
        apply_env: If True, apply MURU_* environment variable overrides.

    Returns:
        A validated Config object.

    Raises:
        FileNotFoundError: If default_path doesn't exist.
        ValueError: If any YAML is malformed or any value fails validation.
    """
    if default_path is None:
        default_path = (
            Path(__file__).resolve().parent.parent.parent.parent / "config" / "default.yaml"
        )

    if not default_path.exists():
        raise FileNotFoundError(
            f"Default config not found at {default_path}. This file should ship with the project."
        )

    if user_path is None:
        user_path = Path("~/.config/muru/config.yaml").expanduser()

    merged = _read_yaml(default_path)
    log.debug("config_defaults_loaded", path=str(default_path))

    user_dict = _read_yaml(user_path)
    if user_dict:
        merged = _deep_merge(merged, user_dict)
        log.debug("config_user_overrides_loaded", path=str(user_path))

    if apply_env:
        merged = _apply_env_overrides(merged)

    config = Config(**merged)
    log.info(
        "config_loaded",
        default_profile=config.llm.default_profile,
        fast_model=config.llm.fast,
        deep_model=config.llm.deep,
        log_level=config.logging.level,
    )
    return config


__all__ = [
    "Config",
    "LLMConfig",
    "LoggingConfig",
    "ModelProfile",
    "PathsConfig",
    "load_config",
]
