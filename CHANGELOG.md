# Changelog

All notable changes to Muru will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

(Nothing yet — Phase 1 feature work begins in v0.2.0)

## [0.1.0] - 2026-05-04

Foundation release. Establishes the core infrastructure that every future
version builds on. Conversation works end-to-end against a local LLM via
Ollama, but no tool execution, no risk classification, no audit, no undo —
those land in v0.2.0+.

### Added
- Project scaffolding (src layout, packages, tests, docs)
- Apache 2.0 license
- Professional Python project configuration via `pyproject.toml`
- Production dependencies: ollama, rich, pyyaml, pydantic, structlog
- Dev tooling: pytest, ruff, mypy (strict mode)
- Structured logging with two output modes (human-readable / JSON)
- Pydantic-validated three-layer config (defaults / user file / env vars)
- Multi-profile LLM model selection (fast / balanced / deep)
- Ollama client with retry logic, model availability check, custom exceptions
- Interactive CLI REPL via `python -m muru` (or `muru` after pip install)
- Welcome banner, help command, graceful exit, Ctrl-C handling
- 62 unit tests + 1 integration test, all passing

### Notes
- Default fast/balanced model: `llama3.1:8b`
- Default deep model: `deepseek-r1:70b`
- Both can be overridden via config or `MURU_LLM_*` env vars
- Integration tests skipped by default; run with `pytest -m integration`

[Unreleased]: https://github.com/drk230513/muru-os/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/drk230513/muru-os/releases/tag/v0.1.0
