"""Controller interface.

A controller gets a state snapshot and returns (heating_c, cooling_c), or
None for no change. Controllers may propose anything; guardrails.validate
sits between them and the actuators.
"""


class Controller:
    name = "base"

    # False means no actuator handles are acquired at all, so the IDF
    # schedules run untouched. Only the baseline sets this.
    actuates = True

    def decide(self, snapshot: dict):
        """Return (heating_setpoint_c, cooling_setpoint_c) or None."""
        raise NotImplementedError
