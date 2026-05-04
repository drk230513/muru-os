# Muru — Project Roadmap

This document is the **single source of truth** for what Muru is and how we build it.
If anything in code or other docs conflicts with this file, this file wins.

## Vision

To create an AI-native operating system where users state their intent in natural
language, and the system autonomously plans and executes the work — pausing only
when human confirmation is genuinely needed.

## Core Principles (Apply to Every Phase)

1. **Intent over instruction** — users describe outcomes, not steps
2. **Autonomous but not unsupervised** — Muru acts on its own within user-controlled confirmation policies
3. **Safety by tier** — every action risk-classified; risk determines confirmation level
4. **Transparent** — every action logged, every decision auditable
5. **Reversible by default** — undo wherever physically possible
6. **Local-first** — open-source LLMs running on the user's machine
7. **Open source** — Apache 2.0
8. **Built on Linux** — we don't reinvent the kernel

## Locked Decisions

| Element | Value |
|---------|-------|
| Brand name | Muru |
| Python package | `muru` |
| CLI command | `muru` |
| GitHub repo | github.com/drk230513/muru-os |
| License | Apache 2.0 |
| Base OS | Ubuntu Linux |
| Primary language | Python (Rust for Phase 4 components) |
| Inference runtime | Ollama (Phase 1–2), vLLM optional (Phase 3+) |
| Vector DB | Qdrant |
| Desktop framework | Tauri (Phase 2+) |
| Embedding model | nomic-embed-text |
| Default LLM | Llama 3.1 8B |

## Phase 1 — The Skateboard (CLI AI Assistant)

**Mission:** Working command-line AI assistant. The core loop end-to-end.

**Success criterion:** User can type "list the Python files in my Downloads folder
modified in the last week" and Muru does it — including refusing or confirming
when appropriate.

### Includes

- Foundation: project structure, logging, config, tests, git workflow
- LLM integration: Ollama client, prompt templates, response parsing, retry logic
- Tool registry: ~8 tools (filesystem read/write, search, info, sandboxed shell)
- Risk classifier (5 tiers, config-driven)
- Confirmation engine (silent / notify-after / confirm-before / strong-confirm / blocked)
- Audit log (JSON-lines, every event)
- Undo system (filesystem ops)
- Sandboxing (working-directory boundary, path traversal prevention, shell whitelist)
- CLI interface (REPL with `rich`, command history)
- Single-step execution only

### Excludes (deferred to later phases)

- GUI, voice, network/web tools, app control, long-term memory, multi-agent,
  generative UI, background daemons, custom distribution

### Versions

- v0.1.0 — Foundation
- v0.2.0 — Read-only filesystem tools
- v0.3.0 — Risk classifier + confirmation engine
- v0.4.0 — Write filesystem tools
- v0.5.0 — Audit log + undo
- v0.6.0 — Sandboxed shell tool
- v0.7.0 — CLI polish
- v0.8.0 — Test coverage + hardening
- **v1.0.0 — Phase 1 release**

**Timeline:** 6–10 weeks part-time

## Phase 2 — The Bicycle (Desktop GUI + Multi-Agent)

**Mission:** Useful daily-driver desktop assistant with multi-agent intelligence.

**Success criterion:** "Find every receipt PDF from 2024 in my documents, summarize
the total amount, and draft an email to my accountant" — Muru plans, executes,
confirms at the right moments, and produces the result.

### Includes (everything from Phase 1, plus)

- Tauri desktop UI (chat interface, audit panel, system tray)
- Semantic memory (Qdrant + nomic-embed-text)
- Multi-step planner (with backtracking, partial completion)
- Expanded tools (~30–50): document readers, web tools, system info, productivity
- App integration framework + MCP client
- Improved confirmation UX (visual diff, impact display, learned trust)
- Smart risk classification (context-aware)
- Generative UI for specific task types
- Background tasks with progress reporting
- Prompt-injection defenses
- Settings UI
- **Multi-agent foundation:** executor + reviewer (sequential, not concurrent)

### Versions

- v1.1.0 — Tauri shell + chat UI
- v1.2.0 — Semantic memory
- v1.3.0 — Multi-step planner
- v1.4.0 — Document tools
- v1.5.0 — Web tools
- v1.6.0 — System tools
- v1.7.0 — App integration + MCP
- v1.8.0 — Generative UI
- v1.9.0 — Smart risk classification
- v1.10.0 — Multi-agent foundation
- **v2.0.0 — Phase 2 release**

**Timeline:** 4–6 months part-time

## Phase 3 — The Motorcycle (Voice + Advanced Multi-Agent)

**Mission:** Voice-first interaction, sophisticated multi-agent collaboration,
system-level integration. Muru becomes ambient.

**Success criterion:** "Hey Muru, while I'm in this meeting, monitor my inbox for
anything from the legal team and prepare a summary by lunch" — a background agent
does exactly that, surfacing only when needed.

### Includes (everything from Phase 2, plus)

- Voice (Whisper STT + Piper TTS, push-to-talk → wake word, barge-in)
- Concurrent multi-agent runtime
- Expanded agent types: monitor, researcher, scheduler, summarizer, reviewer, executor
- Dynamic agent spawning + inter-agent message bus
- Shared context management
- Resource governance (GPU scheduling)
- Background daemons + scheduled tasks
- D-Bus + systemd integration
- Voice/biometric/scheduled confirmations
- Performance optimization

### Versions

- v2.1.0 — Voice input
- v2.2.0 — Voice output
- v2.3.0 — Wake word
- v2.4.0 — Conversational flow
- v2.5.0 — Concurrent multi-agent
- v2.6.0 — Expanded agent types
- v2.7.0 — Dynamic spawning
- v2.8.0 — Background daemons
- v2.9.0 — System integration
- v2.10.0 — Performance pass
- **v3.0.0 — Phase 3 release**

**Timeline:** 3–5 months part-time

## Phase 4 — The Car (Real OS — Custom Distribution)

**Mission:** Bootable, distributable operating system. This is when "Muru" becomes
"Muru OS" legitimately.

**Success criterion:** Someone downloads a Muru OS ISO, installs it on a clean
machine, and never sees "Ubuntu" anywhere unless they go looking. Muru *is* their
computing experience from boot to shutdown.

### Includes (everything from Phase 3, plus)

- Custom Ubuntu-based ISO with Muru branding
- Muru shell as default Wayland session (replaces GNOME/KDE)
- Custom installer
- Update system (atomic, rollback)
- Hardware support pass + live USB
- Distribution infrastructure (website, downloads, docs site, forum)
- Branding & marketing assets
- Complete user/admin/developer documentation

### Versions

- v3.1.0 — ISO build pipeline
- v3.2.0 — Custom branding
- v3.3.0 — Muru as Wayland session (alongside GNOME)
- v3.4.0 — Muru as default session
- v3.5.0 — Custom installer
- v3.6.0 — Update system
- v3.7.0 — Hardware support
- v3.8.0 — Documentation + website
- v3.9.0 — Beta release
- **v4.0.0 — Muru OS 1.0**

**Timeline:** 4–8 months part-time

## Total Realistic Timeline

| Effort | Phase 1 | Phase 2 | Phase 3 | Phase 4 | Total |
|--------|---------|---------|---------|---------|-------|
| Part-time (10h/wk) | 6–10 wks | 4–6 mo | 3–5 mo | 4–8 mo | **18–30 mo** |
| Full-time | 1.5–2.5 wks | 1–1.5 mo | 0.75–1.25 mo | 1–2 mo | **9–15 mo** |

## Scope Discipline

Anything new that someone wants to add gets logged in a `Future` section below.
We revisit between phases — never mid-phase.

### Future / Deferred Ideas

(Empty for now. Will fill as ideas come up.)
