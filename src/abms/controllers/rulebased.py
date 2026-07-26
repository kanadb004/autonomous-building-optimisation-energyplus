"""Occupancy-based setback controller (§2.2) -- also the LLM-failure
fallback from Phase 4 onward. Deep setback when no zone is occupied,
comfortable setpoints when any zone is occupied. Deliberately simple: the
insurance-policy controller, not the one doing the interesting reasoning.
"""

from abms.controllers.base import Controller

OCCUPIED_HEAT_C = 21.0
OCCUPIED_COOL_C = 24.0
# Deeper than the baseline's modest fixed night setback (18/27, see
# models/building.idf), but not maximally deep -- a smart, occupancy-aware
# controller earns its keep through cadence (15-min decisions vs. a static
# weekly program) and depth together, not depth alone (§7 Phase 2: >30%
# savings vs. a defensible baseline is a "suspect a broken baseline" smell).
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
