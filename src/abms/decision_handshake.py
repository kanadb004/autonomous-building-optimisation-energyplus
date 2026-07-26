"""The decision handshake.

At a decision point the sim thread blocks on a queue with a timeout, then
proceeds with either the MCP client's decision or the fallback
controller's.

It sits in its own module because both sides need it without importing
each other: mcp_bridge calls request_decision from the sim thread, and the
set_zone_setpoints tool calls submit_decision from the event loop.
"""

import queue
import sys
import threading
from dataclasses import dataclass, field

DEFAULT_TIMEOUT_S = 60.0
# How long set_zone_setpoints waits for the applied result. This is
# in-process work, so a few seconds means a bug, not slowness.
APPLIED_RESULT_TIMEOUT_S = 5.0


@dataclass
class PendingDecision:
    snapshot: dict
    reply_queue: "queue.Queue" = field(default_factory=queue.Queue)
    result_queue: "queue.Queue" = field(default_factory=queue.Queue)
    reasoning: str | None = None


class DecisionHandshake:
    def __init__(self, timeout_s: float = DEFAULT_TIMEOUT_S):
        self.timeout_s = timeout_s
        self.timeout_count = 0
        self._lock = threading.Lock()
        self._pending: PendingDecision | None = None
        self._result_target: PendingDecision | None = None
        # Reasoning from the most recent decision, picked up by
        # MCPBridgeController for the decision log. None on the fallback path.
        self.last_reasoning: str | None = None

    @property
    def awaiting_decision(self) -> bool:
        with self._lock:
            return self._pending is not None

    def pending_snapshot(self) -> dict | None:
        with self._lock:
            return dict(self._pending.snapshot) if self._pending is not None else None

    def request_decision(self, snapshot: dict, fallback):
        """Block on the sim thread until a decision arrives or timeout_s
        passes, in which case fallback() is used instead.

        Returns the (heating_c, cooling_c) tuple. Guardrails stay the sim
        thread's job and are not applied here.
        """
        pending = PendingDecision(snapshot=snapshot)
        with self._lock:
            self._pending = pending
        try:
            try:
                decision = pending.reply_queue.get(timeout=self.timeout_s)
                self.last_reasoning = pending.reasoning
            except queue.Empty:
                self.timeout_count += 1
                print(
                    f"[decision_handshake] TIMEOUT after {self.timeout_s}s waiting for an MCP "
                    f"decision at sim time {snapshot.get('timestamp')}, falling back to the "
                    f"rule-based controller. (timeout #{self.timeout_count})",
                    file=sys.stderr,
                    flush=True,
                )
                decision = fallback()
                self.last_reasoning = None
            with self._lock:
                self._result_target = pending
            return decision
        finally:
            with self._lock:
                if self._pending is pending:
                    self._pending = None

    def submit_decision(
        self, heating_c: float, cooling_c: float, reasoning: str | None = None
    ) -> PendingDecision | None:
        """Hand a decision to the waiting sim thread.

        Returns the PendingDecision so the caller can wait on its
        result_queue, or None if nothing is pending, e.g. the write tool
        was called outside a decision window or the timeout already fired.
        """
        with self._lock:
            pending = self._pending
        if pending is None:
            return None
        pending.reasoning = reasoning
        pending.reply_queue.put((heating_c, cooling_c))
        return pending

    def publish_result(self, entry: dict) -> None:
        """Deliver the applied result back to the waiting set_zone_setpoints
        call. Called from SimulationRunner's on_decision hook."""
        with self._lock:
            pending = self._result_target
            self._result_target = None
        if pending is not None:
            pending.result_queue.put(entry)
