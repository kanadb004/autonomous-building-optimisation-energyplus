"""The MCP-driven controller (§3.3): plugs an in-process `DecisionHandshake`
into the `Controller` interface `SimulationRunner` already knows how to
drive. `decide()` is called on the sim thread at each decision point; it
blocks inside the handshake until an MCP client calls `set_zone_setpoints`,
or the timeout fires and a fallback controller's decision is used instead.
"""

from abms.controllers.base import Controller
from abms.decision_handshake import DecisionHandshake


class MCPBridgeController(Controller):
    name = "mcp_bridge"
    actuates = True

    def __init__(self, handshake: DecisionHandshake, fallback_controller: Controller):
        self.handshake = handshake
        self.fallback_controller = fallback_controller

    def decide(self, snapshot: dict):
        return self.handshake.request_decision(
            snapshot, fallback=lambda: self.fallback_controller.decide(snapshot)
        )
