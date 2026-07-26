"""Occupancy-based setback controller, also the fallback when the LLM
fails. Setback when nothing is occupied, comfortable setpoints when
anything is. Kept simple on purpose.
"""

from abms.controllers.base import Controller

OCCUPIED_HEAT_C = 21.0
OCCUPIED_COOL_C = 24.0
# Deeper than the IDF's own night setback of 18/27, but not extreme. Most
# of the gain comes from deciding every 15 minutes, not from depth alone.
UNOCCUPIED_HEAT_C = 18.3
UNOCCUPIED_COOL_C = 28.0


class RuleBasedController(Controller):
    name = "rulebased"
    actuates = True

    def __init__(
        self,
        occupied_heat_c: float = OCCUPIED_HEAT_C,
        occupied_cool_c: float = OCCUPIED_COOL_C,
        unoccupied_heat_c: float = UNOCCUPIED_HEAT_C,
        unoccupied_cool_c: float = UNOCCUPIED_COOL_C,
    ):
        self.occupied_heat_c = occupied_heat_c
        self.occupied_cool_c = occupied_cool_c
        self.unoccupied_heat_c = unoccupied_heat_c
        self.unoccupied_cool_c = unoccupied_cool_c

    def decide(self, snapshot: dict):
        if snapshot["occupied"]:
            return (self.occupied_heat_c, self.occupied_cool_c)
        return (self.unoccupied_heat_c, self.unoccupied_cool_c)
