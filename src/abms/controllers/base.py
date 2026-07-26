"""Controller interface (§2.2). A controller is given a state snapshot dict
(one telemetry record, plus `occupied`/`total_occupant_count` derived by the
caller) and returns a decision: (heating_setpoint_c, cooling_setpoint_c), or
None for "no change." Every decision passes through `guardrails.validate`
before being written to actuators -- controllers may propose anything.
"""


class Controller:
    name = "base"

    # False means the simulation runner never acquires actuator handles or
    # writes to them for this controller -- schedules run exactly as
    # authored, with zero actuation noise. Only the no-op baseline sets this.
    actuates = True

    def decide(self, snapshot: dict):
        """Return (heating_setpoint_c, cooling_setpoint_c) or None."""
        raise NotImplementedError
