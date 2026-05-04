# Changelog

All notable changes to Muru will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

(Nothing yet — Phase 1 v0.3.0 work begins next.)

## [0.2.0] - 2026-05-04

Read-only tool release. Muru can now look at the user's filesystem and
answer real questions about it. The LLM autonomously decides which tool
to call and how to summarize the result.

### Added
- **Tool registry** (`muru.tools.registry`) — central catalog of capabilities.
  Tools register themselves at import time. Provides JSON schemas for
  the LLM to consume.
- **Tool wrapper** (`muru.tools.base.Tool`) — generic base for all tools.
  Pydantic-validated args, Pydantic-validated results, custom exception
  hierarchy.
- **Path safety** (`muru.tools.filesystem._safety`) — every filesystem
  tool resolves user paths through `safe_resolve()`, which expands `~`,
  resolves symlinks, and rejects anything outside the user's home directory.
  Defends against path traversal.
- **`list_directory` tool** — list files and folders with metadata
  (name, type, size, modified time). Glob filtering and optional recursion.
- **`read_file` tool** — read text file contents with size cap and
  configurable encoding.
- **`get_file_info` tool** — detailed metadata for a single file or
  directory: type, size, times, POSIX permissions, MIME type, optional
  SHA-256 hash.
- **`search_files` tool** — find files by name pattern (glob) and/or
  content pattern (regex). Skips noise dirs (.git, node_modules, etc).
- **Planner** (`muru.planner`) — LLM-driven intent → Plan converter.
  Robust JSON parsing handles markdown code blocks and surrounding
  chatter. Retries with corrective feedback on parse failure.
- **Orchestrator** (`muru.orchestrator`) — wires planner + tool registry
  + summarizer into an end-to-end pipeline. Never raises; failures are
  encoded in OrchestratorResult.
- **Summarizer** — LLM call that turns raw tool results into friendly
  natural-language summaries.
- **REPL integration** — `python -m muru` now uses the full pipeline.
  Welcome banner shows tool count; help command lists available tools.
- 163 unit tests + 1 integration test, all passing.

### Notes
- Per tool plan: 2 LLM calls (planner + summarizer), ~5–15s on local 8B model.
- Bigger models (Phase 2 with deepseek-r1:70b) substantially improve quality
  and reduce time per call.
- Path sandbox is the user's home directory. Configurable in Phase 2.

### Known Limitations
- Planner doesn't always set `recursive=true` for "in my X folder" queries
  (polish item for v0.3.0 prompt tuning).
- Summarizer can produce verbose output (target: 200 words, polish item
  for v0.3.0).
- No conversation context across turns — each intent is stateless. The
  orchestrator-receives-history pattern lands in v0.3.0.

## [0.1.0] - 2026-05-04

Foundation release. Establishes the core infrastructure that every future
version builds on.

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
- Interactive CLI REPL via `python -m muru`
- Welcome banner, help command, graceful exit, Ctrl-C handling
- 62 unit tests + 1 integration test, all passing

### Notes
- Default fast/balanced model: `llama3.1:8b`
- Default deep model: `deepseek-r1:70b`
- Both can be overridden via config or `MURU_LLM_*` env vars
- Integration tests skipped by default; run with `pytest -m integration`

[Unreleased]: https://github.com/drk230513/muru-os/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/drk230513/muru-os/releases/tag/v0.2.0
[0.1.0]: https://github.com/drk230513/muru-os/releases/tag/v0.1.0
