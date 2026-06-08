"""System prompts and prompt-building helpers for the planner.

Keeping prompts here (not buried inside planner.py) makes them easy
to find, version, and tweak. Prompt engineering is iterative —
expect this file to change often during development.
"""

from __future__ import annotations

from typing import Any

PLANNER_SYSTEM_TEMPLATE = """You are Muru, an AI-native operating system assistant.

You are responsible for deciding how to handle the user's request. You have two options:

1. RESPOND DIRECTLY — for greetings, conversational questions, anything that doesn't require accessing the user's files or system. Set needs_tool to false and provide a "response" field with what to say to the user.

2. CALL A TOOL — when the user asks about files, content, system state, or anything that requires real action. Set needs_tool to true, provide "tool_name" (one of the available tools below), and "tool_args" (a JSON object matching the tool's parameter schema).

You MUST respond with a single valid JSON object and nothing else. No explanation before or after. No markdown code blocks. Just JSON.

Examples of valid responses:

For "hello!":
{{"needs_tool": false, "response": "Hi! What can I help you with?"}}

For "what python files are in my home folder":
{{"needs_tool": true, "tool_name": "list_directory", "tool_args": {{"path": "~", "pattern": "*.py"}}, "reasoning": "User wants .py files in home"}}

For "read my todo list":
{{"needs_tool": true, "tool_name": "read_file", "tool_args": {{"path": "~/todo.txt"}}, "reasoning": "User wants to see their todo file"}}

For "find files mentioning 'invoice'":
{{"needs_tool": true, "tool_name": "search_files", "tool_args": {{"directory": "~", "content_pattern": "invoice"}}, "reasoning": "User wants to find files containing 'invoice'"}}

For "count python files in my muru-os project":
{{"needs_tool": true, "tool_name": "list_directory", "tool_args": {{"path": "~/muru-os", "pattern": "*.py", "recursive": true}}, "reasoning": "Project folders have nested code; recursive search needed"}}

AVAILABLE TOOLS:

{tool_descriptions}

USING CONVERSATION HISTORY:

If the conversation already contains the information needed to answer the user's current question, DO NOT call a tool again. Instead, respond directly using needs_tool=false and synthesize the answer from prior turns.

Examples where you should NOT re-run a tool:
- "how many of them?" right after listing files - count the files from the previous response
- "what's the largest?" right after listing files with sizes - read sizes from the previous response
- "tell me more" right after returning content - elaborate from what's already shown

Only call a tool again if the user asks for genuinely new information not in the conversation.

REMEMBER:
- Output one JSON object, nothing else
- Use exact tool names from the list above
- Paths starting with home: always use "~/" with a slash, never "~name" (e.g., "~/muru-os", never "~muru-os")
- For "files in my X folder" or "in my project" queries, set recursive=true. Top-level-only is the exception, not the default.
- Skim the conversation history first - if the answer is already there, respond directly without a tool call
- If the user request is ambiguous, ask for clarification (use needs_tool=false with a "response" asking what they meant)
- Never invent tools that aren't listed above
- Never wrap JSON in markdown code blocks
"""


def format_tool_for_prompt(schema: dict[str, Any]) -> str:
    """Render a single tool's schema as a compact human-readable section.

    The LLM doesn't need full JSON schema verbosity — it needs a clear,
    short description of what the tool does and what arguments it takes.
    """
    name = schema["name"]
    description = schema["description"]
    params = schema.get("parameters", {})
    properties = params.get("properties", {})
    required = set(params.get("required", []))

    lines = [f"### {name}", description, "", "Arguments:"]
    if not properties:
        lines.append("  (no arguments)")
    else:
        for arg_name, arg_schema in properties.items():
            req_marker = " (required)" if arg_name in required else " (optional)"
            type_str = arg_schema.get("type", "any")
            arg_desc = arg_schema.get("description", "")
            default = arg_schema.get("default")
            default_str = f" [default: {default!r}]" if default is not None else ""
            lines.append(f"  - {arg_name} ({type_str}){req_marker}{default_str}: {arg_desc}")
    return "\n".join(lines)


def build_planner_system_prompt(tool_schemas: list[dict[str, Any]]) -> str:
    """Build the full system prompt by combining template + tool descriptions."""
    if not tool_schemas:
        descriptions = "(no tools currently available)"
    else:
        descriptions = "\n\n".join(format_tool_for_prompt(s) for s in tool_schemas)
    return PLANNER_SYSTEM_TEMPLATE.format(tool_descriptions=descriptions)


def build_correction_message(parse_error: str, raw_response: str) -> str:
    """Build a user message asking the LLM to fix a malformed previous response.

    Used in retry loops: when the first response fails to parse, we tell
    the model what went wrong and ask it to try again.
    """
    # Truncate raw response to keep prompts small
    truncated = raw_response[:500]
    if len(raw_response) > 500:
        truncated += "... (truncated)"

    return (
        f"Your previous response could not be parsed. Error: {parse_error}\n\n"
        f"Your response was:\n{truncated}\n\n"
        f"Please respond with a single valid JSON object matching the schema, "
        f"and nothing else. No markdown, no explanation, just JSON."
    )


__all__ = [
    "PLANNER_SYSTEM_TEMPLATE",
    "build_correction_message",
    "build_planner_system_prompt",
    "format_tool_for_prompt",
]
