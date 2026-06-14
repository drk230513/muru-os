"""Orchestrator - converts user intent into a complete response.

Workflow:
    1. Use the Planner to convert intent into a Plan
    2. If the plan is conversational, return the response directly
    3. If the plan calls a tool, ask the ConfirmationProvider whether
       to proceed (Tier 0/1 auto-approve)
    4. If approved, invoke the tool via the Registry
    5. If tool succeeded, ask the LLM to summarize for the user
    6. If tool failed, ask the LLM to explain the failure
    7. If user rejected the confirmation, return a polite decline
    8. Return an OrchestratorResult bundling everything

In v0.3.0+ the orchestrator also accepts conversation history so the
planner can do multi-step reasoning ("now look at the largest one"
requires knowing what was just listed).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from muru.llm.client import ChatMessage, LLMClient
from muru.orchestrator.result import OrchestratorResult
from muru.orchestrator.summarizer import summarize_tool_result
from muru.planner.planner import Planner, PlannerError
from muru.policy.audit import AuditEntry
from muru.policy.confirmation import Decision
from muru.tools.base import ToolError
from muru.tools.registry import ToolRegistry
from muru.utils.logging import get_logger

if TYPE_CHECKING:
    from muru.policy.audit import AuditWriter
    from muru.policy.confirmation import ConfirmationProvider

log = get_logger(__name__)


class Orchestrator:
    """Converts user intent into a complete response."""

    def __init__(
        self,
        llm: LLMClient,
        planner: Planner,
        registry: ToolRegistry,
        confirmation_provider: ConfirmationProvider | None = None,
        audit_writer: AuditWriter | None = None,
    ) -> None:
        """Construct an Orchestrator.

        Args:
            llm: LLM client used for tool result summarization.
            planner: The planner that converts intent -> Plan.
            registry: The tool registry the planner draws from.
            confirmation_provider: Optional ConfirmationProvider that
                decides whether to execute tool plans. If None, all
                plans auto-approve (matches v0.2.0 behavior).
            audit_writer: Optional AuditWriter. If provided, every tool
                invocation (success or failure) is appended to the audit
                log. If None, no audit log is written (matches v0.4.0
                behavior).
        """
        self._llm = llm
        self._planner = planner
        self._registry = registry
        self._confirmation_provider = confirmation_provider
        self._audit_writer = audit_writer

    def handle(
        self,
        user_intent: str,
        history: list[ChatMessage] | None = None,
    ) -> OrchestratorResult:
        """Handle a single user intent end-to-end.

        Args:
            user_intent: The user's natural-language request.
            history: Optional conversation history (previous user and
                assistant turns) to give the planner context. The
                current intent should NOT already be in history -
                the orchestrator passes it as a separate parameter.

        Returns:
            OrchestratorResult bundling plan, tool result, response,
            and any errors. Never raises.
        """
        log.info(
            "orchestrator_start",
            intent_chars=len(user_intent),
            history_turns=len(history) if history else 0,
        )

        # Step 1: Plan
        try:
            plan = self._planner.plan(user_intent, history=history)
        except PlannerError as e:
            log.warning("orchestrator_planner_failed", error=str(e))
            return OrchestratorResult(
                intent=user_intent,
                plan=None,
                final_response=("I couldn't figure out how to handle that. Could you rephrase?"),
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

        # Step 2b: Tool invocation - first check confirmation
        assert plan.tool_name is not None
        assert plan.tool_args is not None

        # Look up the tool so we know its risk tier and description
        try:
            tool = self._registry.get(plan.tool_name)
        except Exception as e:
            # Planner picked a tool that's not registered. Shouldn't
            # happen because Planner already validates, but defend
            # against future changes.
            log.warning("orchestrator_unknown_tool", tool=plan.tool_name, error=str(e))
            return OrchestratorResult(
                intent=user_intent,
                plan=plan,
                final_response=(
                    f"I tried to use a tool called {plan.tool_name!r}, "
                    f"but it does not exist. This is a bug."
                ),
                error=f"Unknown tool: {plan.tool_name}",
            )

        # Confirmation gate
        if self._confirmation_provider is not None:
            outcome = self._confirmation_provider.confirm(
                tool_name=tool.name,
                tool_description=tool.description,
                tool_args=plan.tool_args,
                risk_tier=tool.risk_tier,
                reasoning=plan.reasoning,
            )
            if outcome.decision == Decision.REJECTED:
                log.info(
                    "orchestrator_user_declined",
                    tool=plan.tool_name,
                    reason=outcome.reason,
                )
                return OrchestratorResult(
                    intent=user_intent,
                    plan=plan,
                    final_response=(
                        "Okay, I will not run that. Let me know if you want to try something else."
                    ),
                )
            # MODIFIED handling is reserved for Phase 2 GUI. CLI
            # provider never returns it, so we treat anything other
            # than APPROVED as a rejection by being conservative.
            if outcome.decision != Decision.APPROVED:
                log.warning(
                    "orchestrator_unexpected_decision",
                    decision=outcome.decision.value,
                )
                return OrchestratorResult(
                    intent=user_intent,
                    plan=plan,
                    final_response=(
                        "The confirmation step returned an unexpected "
                        "decision. Cancelling for safety."
                    ),
                    error=f"Unexpected decision: {outcome.decision.value}",
                )

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
            self._maybe_audit(
                intent=user_intent,
                tool_name=plan.tool_name,
                tool_args=plan.tool_args or {},
                tool_result={"success": False, "error": str(e)},
                final_response=error_summary,
                error=f"ToolError: {e}",
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
                or "The tool completed, but I could not summarize the result."
            )
            self._maybe_audit(
                intent=user_intent,
                tool_name=plan.tool_name,
                tool_args=plan.tool_args or {},
                tool_result=tool_result_dict,
                final_response=fallback,
                error=f"SummarizerError: {e}",
            )
            return OrchestratorResult(
                intent=user_intent,
                plan=plan,
                tool_result=tool_result_dict,
                final_response=fallback,
                error=f"SummarizerError: {e}",
            )

        log.info("orchestrator_complete", tool=plan.tool_name)
        self._maybe_audit(
            intent=user_intent,
            tool_name=plan.tool_name,
            tool_args=plan.tool_args or {},
            tool_result=tool_result_dict,
            final_response=summary,
            error=None,
        )
        return OrchestratorResult(
            intent=user_intent,
            plan=plan,
            tool_result=tool_result_dict,
            final_response=summary,
        )

    def _maybe_audit(
        self,
        *,
        intent: str,
        tool_name: str,
        tool_args: dict[str, object],
        tool_result: dict[str, object],
        final_response: str,
        error: str | None,
    ) -> None:
        """Append an audit entry if a writer is configured.

        Audit failures are logged but never propagated - the user-facing
        flow must continue even if the disk is full or the audit file
        is locked.
        """
        if self._audit_writer is None:
            return
        try:
            entry = AuditEntry(
                intent=intent,
                tool_name=tool_name,
                tool_args=dict(tool_args),
                tool_result=dict(tool_result),
                final_response=final_response,
                error=error,
            )
            self._audit_writer.append(entry)
        except Exception as e:
            log.warning(
                "orchestrator_audit_failed",
                tool=tool_name,
                error=str(e),
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
