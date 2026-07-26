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
        # Read by SimulationRunner._log_decision right after decide()
        # returns, so the MCP client's reasoning text (if any) lands in
        # decisions.jsonl (§4.3). None on the timeout/fallback path.
        self.last_reasoning = None

    def decide(self, snapshot: dict):
        decision = self.handshake.request_decision(
            snapshot, fallback=lambda: self.fallback_controller.decide(snapshot)
        )
        self.last_reasoning = self.handshake.last_reasoning
        return decision
