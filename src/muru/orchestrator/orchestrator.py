"""Orchestrator — converts user intent into a complete response.

Workflow:
    1. Use the Planner to convert intent into a Plan
    2. If the plan is conversational, return the response directly
    3. If the plan calls a tool, invoke it via the Registry
    4. If the tool succeeded, ask the LLM to summarize for the user
    5. If the tool failed, ask the LLM to explain the failure
    6. Return an OrchestratorResult bundling everything
"""

from __future__ import annotations

from muru.llm.client import LLMClient
from muru.orchestrator.result import OrchestratorResult
from muru.orchestrator.summarizer import summarize_tool_result
from muru.planner.planner import Planner, PlannerError
from muru.tools.base import ToolError
from muru.tools.registry import ToolRegistry
from muru.utils.logging import get_logger

log = get_logger(__name__)


class Orchestrator:
    """Converts user intent into a complete response."""

    def __init__(
        self,
        llm: LLMClient,
        planner: Planner,
        registry: ToolRegistry,
    ) -> None:
        self._llm = llm
        self._planner = planner
        self._registry = registry

    def handle(self, user_intent: str) -> OrchestratorResult:
        """Handle a single user intent end-to-end."""
        log.info("orchestrator_start", intent_chars=len(user_intent))

        # Step 1: Plan
        try:
            plan = self._planner.plan(user_intent)
        except PlannerError as e:
            log.warning("orchestrator_planner_failed", error=str(e))
            return OrchestratorResult(
                intent=user_intent,
                plan=None,
                final_response=(
                    "I couldn't figure out how to handle that. The model "
                    "didn't return a usable plan. Could you rephrase?"
                ),
                error=f"PlannerError: {e}",
            )

        # Step 2a: Pure conversation
        if not plan.needs_tool:
            assert plan.response is not None
            log.info("orchestrator_conversational", chars=len(plan.response))
            return OrchestratorResult(
                intent=user_intent,
                plan=plan,
                final_response=plan.response,
            )

        # Step 2b: Tool invocation
        assert plan.tool_name is not None
        assert plan.tool_args is not None

        log.info(
            "orchestrator_invoking_tool",
            tool=plan.tool_name,
            args=plan.tool_args,
        )

        try:
            tool_result_obj = self._registry.invoke(plan.tool_name, plan.tool_args)
        except ToolError as e:
            log.warning(
                "orchestrator_tool_error",
                tool=plan.tool_name,
                error=str(e),
            )
            error_summary = self._summarize_tool_error(
                user_intent, plan.tool_name, plan.tool_args or {}, str(e)
            )
            return OrchestratorResult(
                intent=user_intent,
                plan=plan,
                tool_result=None,
                final_response=error_summary,
                error=f"ToolError: {e}",
            )

        # Step 3: Summarize result via LLM
        tool_result_dict = tool_result_obj.model_dump()

        try:
            summary = summarize_tool_result(
                llm=self._llm,
                user_intent=user_intent,
                tool_name=plan.tool_name,
                tool_args=plan.tool_args or {},
                tool_result=tool_result_dict,
            )
        except Exception as e:
            log.warning("orchestrator_summarizer_failed", error=str(e))
            fallback = (
                tool_result_dict.get("message")
                or "The tool completed, but I couldn't summarize the result."
            )
            return OrchestratorResult(
                intent=user_intent,
                plan=plan,
                tool_result=tool_result_dict,
                final_response=fallback,
                error=f"SummarizerError: {e}",
            )

        log.info("orchestrator_complete", tool=plan.tool_name)
        return OrchestratorResult(
            intent=user_intent,
            plan=plan,
            tool_result=tool_result_dict,
            final_response=summary,
        )

    def _summarize_tool_error(
        self,
        user_intent: str,
        tool_name: str,
        tool_args: dict[str, object],
        error_message: str,
    ) -> str:
        """Ask the LLM to explain a tool error to the user."""
        try:
            return summarize_tool_result(
                llm=self._llm,
                user_intent=user_intent,
                tool_name=tool_name,
                tool_args=tool_args,
                tool_result={
                    "success": False,
                    "error": error_message,
                    "message": (
                        f"The tool {tool_name!r} could not be called. Reason: {error_message}"
                    ),
                },
            )
        except Exception as e:
            log.warning("orchestrator_error_summarizer_failed", error=str(e))
            return f"I tried to run the {tool_name} tool but it failed: {error_message}"


__all__ = ["Orchestrator"]
