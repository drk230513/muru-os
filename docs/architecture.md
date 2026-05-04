# Muru — System Architecture

This document describes the high-level architecture of Muru. It will evolve as we build.

## Layered Architecture

Muru is organized as a layered system. Each layer has a single responsibility and
talks only to the layers immediately above and below it.
## Component Responsibilities

### User Interface (`src/muru/ui/`)
- Capture user intent (typed, later: voice)
- Display Muru's responses, plans, confirmations
- Render audit log, undo history (Phase 2+)

### Orchestrator (`src/muru/core/`)
- The main loop
- Receives intent from UI
- Calls planner, policy engine, tools, audit in the right order
- Handles errors, retries, undo

### Planner (`src/muru/planner/`)
- Takes natural language intent
- Calls LLM to produce structured plan (tool calls with arguments)
- Validates plan against tool schemas
- Phase 1: single action; Phase 2+: multi-step plans

### LLM Client (`src/muru/llm/`)
- Wraps Ollama
- Manages prompt templates
- Parses responses, handles retries on malformed output
- Model selection from config

### Policy Engine (`src/muru/policy/`)
- **Risk classifier** (`risk/`): assigns each action a tier 0–4
- **Confirmation** (`confirmation/`): per-tier rules for asking the user
- **Audit** (`audit/`): writes every event to JSONL log

### Tool Registry (`src/muru/tools/`)
- Catalog of available capabilities
- Each tool is a single Python module with: JSON schema, validation, implementation
- Subdirectories per category (filesystem, shell, web, apps)
- Sandboxing applied uniformly

### Memory (`src/muru/memory/`)
- Phase 1: short-term context for current task
- Phase 2+: long-term semantic memory via Qdrant + embeddings

### Utilities (`src/muru/utils/`)
- Shared infrastructure: logging, config loading, common helpers
- No business logic here

## Data Flow Example (Phase 1)

User types: *"list python files in Downloads"*

1. **UI** captures the input → passes to Orchestrator
2. **Orchestrator** asks **Planner** for a plan
3. **Planner** prompts **LLM** with intent + tool catalog
4. **LLM** returns: `{"tool": "search_files", "args": {"directory": "~/Downloads", "pattern": "*.py"}}`
5. **Planner** validates against the `search_files` schema
6. **Orchestrator** sends the proposed action to **Policy Engine**
7. **Policy Engine** classifies risk → Tier 0 (read-only) → no confirmation needed
8. **Orchestrator** invokes the tool from **Tool Registry**
9. **Tool** runs with sandboxing → returns results
10. **Orchestrator** writes everything to **Audit Log**
11. **Orchestrator** sends results to **UI**
12. **UI** displays formatted output

## Design Decisions

Key decisions are recorded in `docs/decisions/` as Architecture Decision Records (ADRs).

## Evolution by Phase

- **Phase 1:** This document covers the architecture
- **Phase 2:** Add Tauri shell layer, semantic memory layer, multi-agent layer
- **Phase 3:** Add voice layer, agent communication bus, daemon manager
- **Phase 4:** Add Wayland compositor layer, distribution build pipeline

Each phase adds layers without rewriting existing ones — that's the point of the
clean architecture.
