"""Plugs the decision handshake into the Controller interface.

decide() runs on the sim thread and blocks until an MCP client calls
set_zone_setpoints, or until the timeout fires and the fallback is used.
"""

from abms.controllers.base import Controller
from abms.decision_handshake import DecisionHandshake


class MCPBridgeController(Controller):
    name = "mcp_bridge"
    actuates = True

    def __init__(self, handshake: DecisionHandshake, fallback_controller: Controller):
        self.handshake = handshake
        self.fallback_controller = fallback_controller
        # Read straight after decide() so the client's reasoning reaches
        # decisions.jsonl. None on the fallback path.
        self.last_reasoning = None

    def decide(self, snapshot: dict):
        decision = self.handshake.request_decision(
            snapshot, fallback=lambda: self.fallback_controller.decide(snapshot)
        )
        self.last_reasoning = self.handshake.last_reasoning
        return decision
