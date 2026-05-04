"""LLM-based summarization of tool results.

When a tool runs, the orchestrator hands the result to the LLM and asks
it to summarize for the user in natural language. This avoids dumping
raw JSON or technical details into the chat.
"""

from __future__ import annotations

import json
from typing import Any

from muru.llm.client import ChatMessage, LLMClient
from muru.utils.logging import get_logger

log = get_logger(__name__)


SUMMARIZER_SYSTEM_PROMPT = """You are Muru, an AI-native operating system assistant.

A tool was just run on behalf of the user. Your job is to summarize the result for them in natural, friendly language.

Rules:
- Be concise. Don't repeat metadata that doesn't matter to the user.
- If the tool succeeded, present the most useful information first.
- If the tool failed, explain what went wrong in plain English (don't blame the user).
- For lists of items, format them readably (bullet points or short prose).
- For file contents, show the content directly with brief framing.
- Never output JSON or technical jargon unless the user asked for it.
- Don't apologize excessively. Be matter-of-fact.

You will receive:
- The user's original request
- The tool that was called and its arguments
- The tool's result (as JSON)

Respond with a clear, friendly summary."""


def summarize_tool_result(
    llm: LLMClient,
    user_intent: str,
    tool_name: str,
    tool_args: dict[str, Any],
    tool_result: dict[str, Any],
) -> str:
    """Ask the LLM to write a user-friendly summary of a tool result."""
    user_message = (
        f"User asked: {user_intent}\n\n"
        f"I called the tool `{tool_name}` with these arguments:\n"
        f"{json.dumps(tool_args, indent=2)}\n\n"
        f"The tool returned:\n"
        f"{json.dumps(tool_result, indent=2, default=str)}\n\n"
        f"Please write a clear, friendly summary for the user."
    )

    messages: list[ChatMessage] = [
        {"role": "system", "content": SUMMARIZER_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    log.info(
        "summarizer_request",
        tool=tool_name,
        result_keys=list(tool_result.keys()),
    )

    response = llm.chat(messages)

    log.info("summarizer_response", chars=len(response))
    return response


__all__ = ["SUMMARIZER_SYSTEM_PROMPT", "summarize_tool_result"]
