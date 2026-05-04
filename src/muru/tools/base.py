"""Base classes and protocols for Muru tools.

A "tool" is a Python function the LLM can invoke through Muru's planner.
Each tool has:
    - A unique name (string identifier)
    - A description (what it does, for the LLM to read)
    - A Pydantic args model (what arguments it accepts)
    - A Pydantic result model (what it returns)
    - An implementation function

Every tool is wrapped in a Tool instance and registered with the
ToolRegistry. The registry handles lookup, schema generation for the
LLM, and validated invocation.

Tools are *pure functions of their arguments* (modulo filesystem effects).
This makes them easy to test, easy to sandbox, and easy to reason about.

Usage (as a tool author):
    from pydantic import BaseModel
    from muru.tools.base import Tool, ToolResult

    class MyArgs(BaseModel):
        path: str

    class MyResult(BaseModel):
        contents: str

    def my_impl(args: MyArgs) -> MyResult:
        return MyResult(contents=open(args.path).read())

    my_tool = Tool(
        name="my_tool",
        description="Reads a file",
        args_model=MyArgs,
        result_model=MyResult,
        implementation=my_impl,
    )
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field, ValidationError

from muru.policy.risk import RiskTier
from muru.utils.logging import get_logger

log = get_logger(__name__)


# Type parameters: each tool has its own argument and result types.
# Generic[ArgsT, ResultT] lets the type checker know the tool returns
# its declared result type, not Any.
ArgsT = TypeVar("ArgsT", bound=BaseModel)
ResultT = TypeVar("ResultT", bound=BaseModel)


class ToolError(Exception):
    """Base class for tool-related errors."""


class ToolNotFoundError(ToolError):
    """Raised when a tool is requested by name but not registered."""


class ToolValidationError(ToolError):
    """Raised when arguments fail validation against the tool's schema."""


class ToolExecutionError(ToolError):
    """Raised when a tool's implementation itself raises an error.

    The original exception is preserved as `__cause__`.
    """


class ToolResult(BaseModel):
    """Common base for tool results — every tool returns at least success/message.

    Tools subclass this to add their specific fields.
    """

    success: bool = Field(default=True, description="Did the tool succeed?")
    message: str = Field(default="", description="Human-readable summary.")


class Tool(Generic[ArgsT, ResultT]):
    """Wrapper around a tool implementation.

    Holds metadata (name, description), the Pydantic models for args/result,
    and a reference to the implementation function.

    The registry calls invoke() to safely run a tool: it validates args
    through the Pydantic model first, catches and wraps errors.
    """

    def __init__(
        self,
        name: str,
        description: str,
        args_model: type[ArgsT],
        result_model: type[ResultT],
        implementation: Callable[[ArgsT], ResultT],
        risk_tier: RiskTier = RiskTier.READ_ONLY,
    ) -> None:
        if not name or not name.replace("_", "").isalnum():
            raise ValueError(f"Tool name must be non-empty alphanumeric/underscore, got {name!r}")
        if not description.strip():
            raise ValueError("Tool description must not be empty.")

        self.name = name
        self.description = description
        self.args_model = args_model
        self.result_model = result_model
        self.risk_tier = risk_tier
        self._implementation = implementation

    def invoke(self, raw_args: dict[str, Any]) -> ResultT:
        """Validate raw_args, run the tool, return the result.

        Args:
            raw_args: Dict of arguments (typically from the LLM's tool call).

        Returns:
            A validated result of the tool's declared result type.

        Raises:
            ToolValidationError: If raw_args don't match the args schema.
            ToolExecutionError: If the implementation itself raises.
        """
        try:
            args = self.args_model(**raw_args)
        except ValidationError as e:
            log.warning(
                "tool_args_validation_failed",
                tool=self.name,
                raw_args=raw_args,
                errors=e.errors(),
            )
            raise ToolValidationError(f"Invalid args for tool {self.name!r}: {e}") from e

        log.debug("tool_invoking", tool=self.name, args=raw_args)
        try:
            result = self._implementation(args)
        except Exception as e:
            log.warning("tool_execution_failed", tool=self.name, error=str(e))
            raise ToolExecutionError(f"Tool {self.name!r} raised {type(e).__name__}: {e}") from e

        log.debug("tool_completed", tool=self.name)
        return result

    def schema(self) -> dict[str, Any]:
        """Return a JSON-schema-style description of this tool for the LLM.

        The LLM uses this to know what arguments to provide.
        Format follows the OpenAI/Anthropic tool-call convention so the LLM
        is on familiar ground.
        """
        return {
            "name": self.name,
            "description": self.description,
            "risk_tier": int(self.risk_tier),
            "risk_tier_label": self.risk_tier.display_name,
            "parameters": self.args_model.model_json_schema(),
        }


__all__ = [
    "Tool",
    "ToolError",
    "ToolExecutionError",
    "ToolNotFoundError",
    "ToolResult",
    "ToolValidationError",
]
