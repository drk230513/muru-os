# Muru

> An AI-native operating system built on the Linux kernel

Muru is an intent-based computing platform where users state what they want in natural language, and the system autonomously plans and executes the work — pausing only for human confirmation when needed.

## Status

🚧 **Pre-alpha — Phase 1 in active development**

Current version: `v0.1.0-dev` (Foundation)

## Vision

Most computing time is spent translating *what we want* into *how to make the computer do it* — clicking through menus, remembering commands, switching apps. Muru collapses that translation. You say what you want; Muru figures out how.

### Core Principles

1. **Intent over instruction** — describe outcomes, not steps
2. **Autonomous but not unsupervised** — acts on its own within user-controlled confirmation policies
3. **Safety by tier** — every action risk-classified; risk determines confirmation level
4. **Transparent** — every action logged, every decision auditable
5. **Reversible by default** — undo wherever physically possible
6. **Local-first** — open-source LLMs running on the user's machine
7. **Open source** — Apache 2.0; the user owns their OS
8. **Built on Linux** — the AI layer is where the innovation happens

## Roadmap

This project is being built in four disciplined phases:

- **Phase 1 — The Skateboard:** CLI AI assistant with tool execution, risk-tiered confirmation, audit log, undo
- **Phase 2 — The Bicycle:** Tauri desktop GUI, semantic memory, multi-step planning, multi-agent (executor + reviewer)
- **Phase 3 — The Motorcycle:** Voice (STT/TTS, wake word), concurrent multi-agent, background daemons, system integration
- **Phase 4 — The Car:** Custom Linux distribution, Muru shell as default session, bootable ISO — the first version legitimately called "Muru OS"

See [`docs/roadmap.md`](docs/roadmap.md) for the complete specification.

## Tech Stack

- **Language:** Python (orchestrator), Rust (Phase 4 components)
- **LLM runtime:** Ollama (local inference)
- **Default model:** Llama 3.1 8B (configurable)
- **Vector DB:** Qdrant (Phase 2+)
- **Desktop framework:** Tauri (Phase 2+)
- **Base OS:** Ubuntu 24.04 LTS

## Getting Started

> Coming with v0.1.0 release. Currently bootstrapping the foundation.

## Contributing

This is currently a solo development project, but contributions will be welcomed once Phase 1 ships. See [`docs/architecture.md`](docs/architecture.md) for the system design.

## License

Apache License 2.0 — see [`LICENSE`](LICENSE) for full text.
