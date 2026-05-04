"""Parse LLM responses into structured Plan objects.

Open-source LLMs (especially smaller ones) often:
- Wrap JSON in markdown code blocks (```json ... ```)
- Add chatter before or after the JSON
- Include trailing commas, single quotes, or other almost-JSON tics
- Forget to close braces

This module's job is to extract a valid JSON object from messy output
and validate it against the Plan schema. Returns either a Plan or
raises PlanParseError with a helpful message that can be sent back
to the LLM for correction.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from muru.planner.plan import Plan


class PlanParseError(Exception):
    """Raised when an LLM response cannot be parsed into a valid Plan."""


# Match a code block: ```json ... ``` or ``` ... ```
_CODE_BLOCK_RE = re.compile(
    r"```(?:json)?\s*(.+?)\s*```",
    re.DOTALL,
)


def _extract_json_string(raw: str) -> str:
    """Pull a JSON object out of a possibly-messy LLM response.

    Strategies, in order:
      1. Look for ```json ... ``` or ``` ... ``` code blocks.
      2. Look for the first { and the matching }.
      3. Give up and return the original string (let json.loads complain).
    """
    raw = raw.strip()

    # Strategy 1: code block
    match = _CODE_BLOCK_RE.search(raw)
    if match:
        return match.group(1).strip()

    # Strategy 2: find first { and matching }
    start = raw.find("{")
    if start == -1:
        return raw  # No JSON object visible

    # Brace matching with respect for strings
    depth = 0
    in_string = False
    escape = False
    for i, char in enumerate(raw[start:], start=start):
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return raw[start : i + 1]

    # Unclosed braces — return what we have
    return raw[start:]


def parse_plan(raw_response: str) -> Plan:
    """Parse a raw LLM response into a validated Plan.

    Args:
        raw_response: The string the LLM returned.

    Returns:
        A validated Plan object.

    Raises:
        PlanParseError: If the response can't be parsed or doesn't validate.
            The error message is suitable for sending back to the LLM
            via build_correction_message().
    """
    if not raw_response or not raw_response.strip():
        raise PlanParseError("Empty response from LLM.")

    json_str = _extract_json_string(raw_response)

    try:
        data: Any = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise PlanParseError(
            f"Response is not valid JSON: {e.msg} (line {e.lineno}, col {e.colno})"
        ) from e

    if not isinstance(data, dict):
        raise PlanParseError(f"Top-level JSON value must be an object, got {type(data).__name__}.")

    try:
        return Plan(**data)
    except ValidationError as e:
        # Pydantic's error message is detailed; trim it for the LLM
        first_error = e.errors()[0] if e.errors() else None
        if first_error:
            field = ".".join(str(loc) for loc in first_error["loc"])
            msg = first_error["msg"]
            raise PlanParseError(f"Plan failed validation at field {field!r}: {msg}") from e
        raise PlanParseError(f"Plan failed validation: {e}") from e


__all__ = ["PlanParseError", "parse_plan"]
