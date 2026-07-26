"""No-op controller: the IDF's own schedules run untouched."""

from abms.controllers.base import Controller


class BaselineController(Controller):
    name = "baseline"
    actuates = False

    def decide(self, snapshot: dict):
        return None
