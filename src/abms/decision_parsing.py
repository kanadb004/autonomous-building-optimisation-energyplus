"""Malformed-LLM-output handling (§4.4, §6 trap #7): validates the LLM's
JSON decision object against a strict schema. Guardrail *value* clamping
(absurd-but-well-typed setpoints) happens later, in guardrails.py -- this
module only rejects structurally invalid replies (bad JSON, missing/
wrong-typed fields, non-finite numbers) so the runner's repair-retry-then-
fallback logic (§4.1, §4.4) has one narrow failure signal to act on.
"""

import json
import math
import re

from pydantic import BaseModel, Field, ValidationError, field_validator


class DecisionParseError(ValueError):
    """Raised when the model's raw reply cannot be turned into a valid
    Decision -- malformed JSON, missing fields, or non-finite numbers."""


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
    """Parse and validate one LLM reply. Tries a strict `json.loads` first;
    if the model wrapped the object in stray prose or markdown fences
    despite the JSON-mode request, falls back to extracting the first
    `{...}` block before giving up. Raises `DecisionParseError` with a
    human-readable reason on any failure -- the caller (llm_agent.py) uses
    that message both for its repair-retry prompt and for logging."""
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
