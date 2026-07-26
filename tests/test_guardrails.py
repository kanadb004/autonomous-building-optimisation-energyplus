"""Guardrail tests: bounds, deadband, step limit, occupied floor.

Every clamp gets a case where it should fire and one where it shouldn't.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from abms import guardrails  # noqa: E402


def test_passthrough_when_within_bounds_and_step():
    result = guardrails.validate(21.0, 24.0, prev_heating_c=21.0, prev_cooling_c=24.0, occupied=True)
    assert result.heating_c == 21.0
    assert result.cooling_c == 24.0
    assert result.notes == []


def test_heating_clamped_to_max():
    result = guardrails.validate(30.0, 32.0, prev_heating_c=23.0, prev_cooling_c=32.0, occupied=False)
    assert result.heating_c == guardrails.HEATING_MAX_C
    assert result.clamped


def test_heating_clamped_to_min():
    result = guardrails.validate(5.0, 22.0, prev_heating_c=12.0, prev_cooling_c=22.0, occupied=False)
    assert result.heating_c == guardrails.HEATING_MIN_C


def test_cooling_clamped_to_max():
    result = guardrails.validate(15.0, 40.0, prev_heating_c=15.0, prev_cooling_c=32.0, occupied=False)
    assert result.cooling_c == guardrails.COOLING_MAX_C


def test_cooling_clamped_to_min():
    result = guardrails.validate(15.0, 10.0, prev_heating_c=15.0, prev_cooling_c=22.0, occupied=False)
    assert result.cooling_c == guardrails.COOLING_MIN_C


def test_max_step_limits_heating_increase():
    # Big jump requested (15 -> 21, 6C) should be capped to MAX_STEP_C.
    result = guardrails.validate(21.0, 30.0, prev_heating_c=15.0, prev_cooling_c=30.0, occupied=False)
    assert result.heating_c == 15.0 + guardrails.MAX_STEP_C


def test_max_step_limits_cooling_decrease():
    result = guardrails.validate(15.0, 24.0, prev_heating_c=15.0, prev_cooling_c=30.0, occupied=False)
    assert result.cooling_c == 30.0 - guardrails.MAX_STEP_C


def test_max_step_allows_small_change():
    result = guardrails.validate(16.0, 29.0, prev_heating_c=15.0, prev_cooling_c=30.0, occupied=False)
    assert result.heating_c == 16.0
    assert result.cooling_c == 29.0


def test_deadband_enforced_when_setpoints_too_close():
    result = guardrails.validate(22.0, 22.5, prev_heating_c=22.0, prev_cooling_c=22.5, occupied=False)
    assert result.cooling_c - result.heating_c >= guardrails.MIN_DEADBAND_C


def test_deadband_not_triggered_when_already_satisfied():
    result = guardrails.validate(21.0, 24.0, prev_heating_c=21.0, prev_cooling_c=24.0, occupied=True)
    assert not any("deadband" in n for n in result.notes)


def test_occupied_heat_floor_overrides_low_request():
    # Deep setback values requested while occupied -- floor must win.
    result = guardrails.validate(18.3, 28.0, prev_heating_c=18.3, prev_cooling_c=28.0, occupied=True)
    assert result.heating_c == guardrails.OCCUPIED_HEAT_FLOOR_C


def test_occupied_cool_ceiling_overrides_high_request():
    result = guardrails.validate(18.3, 28.0, prev_heating_c=18.3, prev_cooling_c=28.0, occupied=True)
    assert result.cooling_c == guardrails.OCCUPIED_COOL_CEILING_C


def test_occupied_floor_not_applied_when_unoccupied():
    result = guardrails.validate(18.3, 28.0, prev_heating_c=18.3, prev_cooling_c=28.0, occupied=False)
    assert result.heating_c == 18.3
    assert result.cooling_c == 28.0


def test_no_clamp_notes_for_clean_occupied_request():
    result = guardrails.validate(21.0, 24.0, prev_heating_c=21.0, prev_cooling_c=24.0, occupied=True)
    assert result.notes == []
    assert not result.clamped
