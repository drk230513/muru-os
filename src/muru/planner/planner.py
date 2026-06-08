"""The Planner — converts user intent into a structured Plan via the LLM.

Workflow:
    1. Build system prompt from registered tool schemas
    2. Send (system + user) to LLM
    3. Parse response into a Plan (with retry on parse failure)
    4. Validate the Plan references a real registered tool
    5. Return the Plan

The Planner does NOT execute the plan — that's the Executor's job
(Chunk 10). The Planner only decides what to do.

Usage:
    from muru.planner.planner import Planner
    from muru.tools.registry import registry
    from muru.llm.client import LLMClient
    from muru.utils.config import load_config

    config = load_config()
    llm = LLMClient(config.llm)
    planner = Planner(llm=llm, registry=registry)

    plan = planner.plan("list my python files")
    if plan.needs_tool:
        print(f"Will call {plan.tool_name} with {plan.tool_args}")
    else:
        print(plan.response)
"""

from __future__ import annotations

from muru.llm.client import ChatMessage, LLMClient
from muru.planner.parser import PlanParseError, parse_plan
from muru.planner.plan import Plan
from muru.planner.prompts import (
    build_correction_message,
    build_planner_system_prompt,
)
from muru.tools.registry import ToolRegistry
from muru.utils.logging import get_logger

log = get_logger(__name__)


class PlannerError(Exception):
    """Raised when the planner fails to produce a valid Plan."""


class Planner:
    """LLM-driven intent → Plan converter."""

    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        max_retries: int = 2,
    ) -> None:
        """Construct a Planner.

        Args:
            llm: An LLMClient (will be called with chat() — multi-turn).
            registry: The tool registry to expose to the LLM.
            max_retries: How many times to retry parse failures with
                corrective feedback. Defaults to 2 (so 3 total attempts).
        """
        self._llm = llm
        self._registry = registry
        self._max_retries = max_retries

    def plan(
        self,
        user_intent: str,
        history: list[ChatMessage] | None = None,
    ) -> Plan:
        """Produce a Plan for the given user intent.

        Args:
            user_intent: The user's natural-language request.

        Returns:
            A validated Plan object.

        Raises:
            PlannerError: If the LLM repeatedly fails to produce a valid
                plan (after max_retries+1 attempts), or if the plan
                references an unknown tool.
        """
        if not user_intent or not user_intent.strip():
            raise PlannerError("user_intent must be a non-empty string.")

        # Build the system prompt with current tool schemas
        tool_schemas = self._registry.schemas_for_llm()
        system_prompt = build_planner_system_prompt(tool_schemas)

        # Build the conversation: system + history + current user turn
        messages: list[ChatMessage] = [
            {"role": "system", "content": system_prompt},
        ]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_intent})

        log.info(
            "planner_request",
            intent_chars=len(user_intent),
            tool_count=len(tool_schemas),
        )

        last_error: str | None = None
        for attempt in range(self._max_retries + 1):
            # On retries, append a corrective user message
            if attempt > 0 and last_error is not None:
                messages.append(
                    {
                        "role": "user",
                        "content": build_correction_message(last_error, messages[-1]["content"]),
                    }
                )

            raw = self._llm.chat(messages)
            log.debug("planner_raw_response", attempt=attempt, response=raw[:200])

            try:
                plan = parse_plan(raw)
            except PlanParseError as e:
                last_error = str(e)
                log.warning(
                    "planner_parse_failed",
                    attempt=attempt,
                    error=last_error,
                )
                # Append the assistant's bad reply for context on retry
                messages.append({"role": "assistant", "content": raw})
                continue

            # Validate that the tool, if any, is real
            if plan.needs_tool:
                assert plan.tool_name is not None  # validator guarantees this
                if plan.tool_name not in self._registry.list_names():
                    last_error = (
                        f"Tool {plan.tool_name!r} is not registered. "
                        f"Available tools: {self._registry.list_names()}"
                    )
                    log.warning(
                        "planner_unknown_tool",
                        attempt=attempt,
                        tool=plan.tool_name,
                    )
                    messages.append({"role": "assistant", "content": raw})
                    continue

            log.info(
                "planner_success",
                attempt=attempt,
                needs_tool=plan.needs_tool,
                tool=plan.tool_name,
            )
            return plan

        raise PlannerError(
            f"Planner failed after {self._max_retries + 1} attempts. Last error: {last_error}"
        )


__all__ = ["Planner", "PlannerError"]
