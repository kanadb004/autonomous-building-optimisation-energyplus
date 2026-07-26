"""Deterministic setpoint validator/clamper (§2.4). Every controller's
decision -- rule-based today, LLM in Phase 4 -- passes through here before
being written to actuators. Every clamp/rejection is logged with a reason
so the decision log carries requested vs. applied values.
"""

from dataclasses import dataclass, field

HEATING_MIN_C = 12.0
HEATING_MAX_C = 23.0
COOLING_MIN_C = 22.0
COOLING_MAX_C = 32.0
MIN_DEADBAND_C = 1.0
MAX_STEP_C = 3.0

# Occupied-hours comfort floor: enforced regardless of what the controller
# asked for (§2.4) -- this is the one guardrail that overrides everything
# else, applied last.
OCCUPIED_HEAT_FLOOR_C = 20.0
OCCUPIED_COOL_CEILING_C = 26.0


@dataclass
class GuardrailResult:
    heating_c: float
    cooling_c: float
    notes: list = field(default_factory=list)

    @property
    def clamped(self) -> bool:
        return bool(self.notes)


def validate(
    requested_heating_c: float,
    requested_cooling_c: float,
    *,
    prev_heating_c: float,
    prev_cooling_c: float,
    occupied: bool,
) -> GuardrailResult:
    """Clamp a requested (heating_c, cooling_c) decision. `prev_*_c` are the
    last *applied* setpoints (for the max-step-per-decision rule); `occupied`
    gates the comfort-floor override. Returns the values to actually write to
    the actuators plus a human-readable note per clamp applied (empty list =
    the request passed through unmodified)."""
    notes = []
    heating_c = requested_heating_c
    cooling_c = requested_cooling_c

    bounded = min(max(heating_c, HEATING_MIN_C), HEATING_MAX_C)
    if bounded != heating_c:
        notes.append(f"heating clamped to bounds [{HEATING_MIN_C}, {HEATING_MAX_C}]: {heating_c} -> {bounded}")
    heating_c = bounded

    bounded = min(max(cooling_c, COOLING_MIN_C), COOLING_MAX_C)
    if bounded != cooling_c:
        notes.append(f"cooling clamped to bounds [{COOLING_MIN_C}, {COOLING_MAX_C}]: {cooling_c} -> {bounded}")
    cooling_c = bounded

    if abs(heating_c - prev_heating_c) > MAX_STEP_C:
        stepped = prev_heating_c + max(-MAX_STEP_C, min(MAX_STEP_C, heating_c - prev_heating_c))
        notes.append(f"heating step limited to {MAX_STEP_C}C/decision: {heating_c} -> {stepped}")
        heating_c = stepped

    if abs(cooling_c - prev_cooling_c) > MAX_STEP_C:
        stepped = prev_cooling_c + max(-MAX_STEP_C, min(MAX_STEP_C, cooling_c - prev_cooling_c))
        notes.append(f"cooling step limited to {MAX_STEP_C}C/decision: {cooling_c} -> {stepped}")
        cooling_c = stepped

    if cooling_c - heating_c < MIN_DEADBAND_C:
        adjusted = min(heating_c + MIN_DEADBAND_C, COOLING_MAX_C)
        notes.append(f"deadband enforced (heating {heating_c} + {MIN_DEADBAND_C}C): cooling {cooling_c} -> {adjusted}")
        cooling_c = adjusted

    if occupied:
        if heating_c < OCCUPIED_HEAT_FLOOR_C:
            notes.append(f"occupied comfort floor: heating {heating_c} -> {OCCUPIED_HEAT_FLOOR_C}")
            heating_c = OCCUPIED_HEAT_FLOOR_C
        if cooling_c > OCCUPIED_COOL_CEILING_C:
            notes.append(f"occupied comfort ceiling: cooling {cooling_c} -> {OCCUPIED_COOL_CEILING_C}")
            cooling_c = OCCUPIED_COOL_CEILING_C

    return GuardrailResult(heating_c=heating_c, cooling_c=cooling_c, notes=notes)
