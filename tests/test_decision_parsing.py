"""Malformed-LLM-output handling tests (§7, §4.4). Covers valid replies,
malformed JSON, missing/wrong-typed fields, and absurd (non-finite) values
-- the runner's repair-retry-then-fallback logic depends on
`DecisionParseError` being raised for exactly these cases and nothing else.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from abms.decision_parsing import DecisionParseError, parse_decision  # noqa: E402


def test_valid_reply_parses():
    decision = parse_decision('{"reasoning": "unoccupied, deep setback", "heating_c": 18.3, "cooling_c": 28.0}')
    assert decision.heating_c == 18.3
    assert decision.cooling_c == 28.0
    assert decision.reasoning == "unoccupied, deep setback"


def test_valid_reply_with_int_setpoints_coerces_to_float():
    decision = parse_decision('{"reasoning": "occupied comfort", "heating_c": 21, "cooling_c": 24}')
    assert decision.heating_c == 21.0
    assert decision.cooling_c == 24.0


def test_reply_wrapped_in_stray_prose_or_markdown_still_parses():
    raw = (
        "Sure, here is my decision:\n```json\n"
        '{"reasoning": "pre-cooling before peak", "heating_c": 21.0, "cooling_c": 23.0}\n```'
    )
    decision = parse_decision(raw)
    assert decision.cooling_c == 23.0


def test_empty_reply_raises():
    with pytest.raises(DecisionParseError):
        parse_decision("")


def test_not_json_raises():
    with pytest.raises(DecisionParseError):
        parse_decision("I think we should cool the building down a bit.")


def test_json_array_not_object_raises():
    with pytest.raises(DecisionParseError):
        parse_decision("[21.0, 24.0]")


def test_missing_heating_field_raises():
    with pytest.raises(DecisionParseError):
        parse_decision('{"reasoning": "x", "cooling_c": 24.0}')


def test_missing_reasoning_field_raises():
    with pytest.raises(DecisionParseError):
        parse_decision('{"heating_c": 21.0, "cooling_c": 24.0}')


def test_empty_reasoning_raises():
    with pytest.raises(DecisionParseError):
        parse_decision('{"reasoning": "", "heating_c": 21.0, "cooling_c": 24.0}')


def test_non_numeric_setpoint_raises():
    with pytest.raises(DecisionParseError):
        parse_decision('{"reasoning": "x", "heating_c": "warm", "cooling_c": 24.0}')


def test_non_finite_setpoint_raises():
    with pytest.raises(DecisionParseError):
        parse_decision('{"reasoning": "x", "heating_c": NaN, "cooling_c": 24.0}')


def test_absurd_but_well_typed_values_still_parse():
    # Physically absurd values are guardrails.py's job, not decision_parsing's --
    # a well-typed, well-shaped reply must parse regardless of magnitude.
    decision = parse_decision('{"reasoning": "x", "heating_c": 999.0, "cooling_c": -50.0}')
    assert decision.heating_c == 999.0
    assert decision.cooling_c == -50.0
