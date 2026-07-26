"""Validates the LLM's JSON decision against a strict schema.

Only structural problems are rejected here: bad JSON, missing or
wrong-typed fields, non-finite numbers. Clamping well-formed but silly
values is guardrails.py's job.
"""

import json
import math
import re

from pydantic import BaseModel, Field, ValidationError, field_validator


class DecisionParseError(ValueError):
    """The model's reply could not be turned into a valid Decision."""


class Decision(BaseModel):
    heating_c: float
    cooling_c: float
    reasoning: str = Field(min_length=1)

    @field_validator("heating_c", "cooling_c")
    @classmethod
    def _finite(cls, v):
        if not math.isfinite(v):
            raise ValueError("setpoint must be a finite number")
        return v


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_decision(raw_text: str) -> Decision:
    """Parse and validate one LLM reply.

    Tries json.loads first, then falls back to pulling out the first
    {...} block if the model wrapped it in prose or markdown fences. The
    error message is reused in the repair-retry prompt.
    """
    text = (raw_text or "").strip()
    if not text:
        raise DecisionParseError("reply was empty")

    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_OBJECT_RE.search(text)
        if not match:
            raise DecisionParseError(f"reply is not valid JSON and contains no JSON object: {text[:200]!r}")
        try:
            obj = json.loads(match.group(0))
        except json.JSONDecodeError as e:
            raise DecisionParseError(f"reply is not valid JSON: {e}") from e

    if not isinstance(obj, dict):
        raise DecisionParseError(f"reply JSON must be an object, got {type(obj).__name__}")

    try:
        return Decision.model_validate(obj)
    except ValidationError as e:
        raise DecisionParseError(f"reply JSON failed schema validation: {e}") from e
