"""No-op controller: schedules run exactly as authored in the IDF (§2.2)."""

from abms.controllers.base import Controller


class BaselineController(Controller):
    name = "baseline"
    actuates = False

    def decide(self, snapshot: dict):
        return None
