# Changelog

All notable changes to Muru will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

(Nothing yet - v0.5.0 work begins next: audit log + undo.)

## [0.4.0] - 2026-06-14

The write release. Muru can now create, modify, move, and delete files
with tier-appropriate confirmation prompts.

### Added
- **`write_file` tool (Tier 3)**: atomic writes via temp+rename, sandboxed
  to user home, captures previous content for v0.5.0 undo
- **`move_file` tool (Tier 3)**: refuses to overwrite existing destination,
  uses shutil.move() for cross-filesystem moves
- **`delete_file` tool (Tier 4)**: red-panel UX with 5s cooldown, must type
  the tool name to confirm. Captures deleted content for v0.5.0 undo
- **Integration tests** in test_repl.py that verify confirmation gating
  end-to-end (catches the spinner bug regression and similar)
- Design doc at `docs/v0.4-write-tools-design.md` documenting tier
  choices, atomic write strategy, undo metadata schema

### Fixed
- **Security bug from v0.3.x**: REPL's status spinner was monopolizing
  the terminal, causing console.input() in the confirmation provider to
  return cached content. The bug auto-approved Tier 2+ confirmations
  without ever showing a prompt. Latent in v0.3.x because all tools
  were Tier 0. Caught by manual testing during v0.4.0-alpha1 work.
- REPL no longer wraps orchestrator.handle() in console.status(); the
  confirmation panel itself provides visual feedback that work is
  happening

### Safety guarantees
- All write tools sandboxed via `safe_resolve()` — refuse paths outside
  user home directory
- `write_file` refuses to clobber directories or non-regular files
- `move_file` refuses to silently overwrite — user must explicitly delete
  the destination first (its own Tier 4 confirmation)
- `delete_file` refuses directories (different UX needed, deferred), and
  for symlinks deletes the link, never the target

### Notes
- Undo metadata is captured in tool results (previous_content,
  deleted_content) but undo itself lands in v0.5.0
- Content capture is capped at 10MB per file. Larger files complete
  but are noted as not undoable from the result alone
- 247 tests passing (was 221 in v0.4.0-alpha1)

## [0.4.0-alpha1] - 2026-06-08

Pre-release: first write tool + critical security fix.

### Added
- `write_file` tool (Tier 3) with atomic writes
- Design doc for v0.4.0 write tools

### Fixed
- Latent v0.3.x spinner-bypasses-confirmation bug (see v0.4.0 notes)

## [0.3.1] - 2026-06-08

Planner prompt polish patch.

### Fixed
- Planner now sets recursive=true for "files in my X folder" queries
- Planner uses "~/" with slash instead of "~name" for home paths
- Planner uses conversation history before re-running tools

## [0.3.0] - 2026-06-08

Confirmation and conversation release.

### Added
- Risk tier system (Tier 0-4) for all tools
- ConfirmationProvider Protocol + CLI implementation (Rich panels)
- Tier-aware confirmation UX (auto, y/n, type-yes, type-name + cooldown)
- Multi-turn conversation history in REPL
- `clear` command to reset history mid-session

### Changed
- Quiet logs by default (set MURU_LOGGING_LEVEL=INFO to debug)
- REPL passes list(history) (defensive copy) to orchestrator

## [0.2.0] - 2026-05-04

Read-only tool release.

### Added
- Tool registry, Pydantic-validated Tool wrapper, path-safety helper
- `list_directory`, `read_file`, `get_file_info`, `search_files`
- LLM-driven planner with robust JSON parsing
- Orchestrator wiring planner + tool registry + summarizer
- REPL integration: `python -m muru` is a working AI assistant

## [0.1.0] - 2026-05-04

Foundation release.

### Added
- Project scaffolding, Apache 2.0 license, pyproject.toml
- Structured logging, Pydantic-validated config, Ollama client
- Interactive CLI REPL via `python -m muru`

[Unreleased]: https://github.com/drk230513/muru-os/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/drk230513/muru-os/releases/tag/v0.4.0
[0.4.0-alpha1]: https://github.com/drk230513/muru-os/releases/tag/v0.4.0-alpha1
[0.3.1]: https://github.com/drk230513/muru-os/releases/tag/v0.3.1
[0.3.0]: https://github.com/drk230513/muru-os/releases/tag/v0.3.0
[0.2.0]: https://github.com/drk230513/muru-os/releases/tag/v0.2.0
[0.1.0]: https://github.com/drk230513/muru-os/releases/tag/v0.1.0
