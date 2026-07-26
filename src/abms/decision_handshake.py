"""The decision handshake (§3.3, §6 steps 4-9): the mechanism by which the
sim thread says "decision point reached," blocks on a response queue with a
wall-clock timeout, and proceeds with either the MCP client's validated
decision or a fallback controller's decision if the timeout fires.

Lives in its own module (rather than inside `mcp_server.py` or a
`Controller` subclass) because both sides need it without importing each
other: `controllers/mcp_bridge.py` calls `request_decision` from the sim
thread; `mcp_server.py`'s `set_zone_setpoints` tool calls `submit_decision`
from the asyncio event loop. Same process, same in-memory queue -- no
serialization, no IPC (§3 architecture decision).
"""

import queue
import sys
import threading
from dataclasses import dataclass, field

DEFAULT_TIMEOUT_S = 60.0
# How long `set_zone_setpoints` waits for the sim thread to guardrail-validate,
# apply, and log a decision it just handed over -- this is local in-process
# work (no I/O), so anything beyond a couple seconds indicates a bug, not
# normal latency.
APPLIED_RESULT_TIMEOUT_S = 5.0


@dataclass
class PendingDecision:
    snapshot: dict
    reply_queue: "queue.Queue" = field(default_factory=queue.Queue)
    result_queue: "queue.Queue" = field(default_factory=queue.Queue)


class DecisionHandshake:
    def __init__(self, timeout_s: float = DEFAULT_TIMEOUT_S):
        self.timeout_s = timeout_s
        self.timeout_count = 0
        self._lock = threading.Lock()
        self._pending: PendingDecision | None = None
        self._result_target: PendingDecision | None = None

    @property
    def awaiting_decision(self) -> bool:
        with self._lock:
            return self._pending is not None

    def pending_snapshot(self) -> dict | None:
        with self._lock:
            return dict(self._pending.snapshot) if self._pending is not None else None

    def request_decision(self, snapshot: dict, fallback):
        """Called on the sim thread at a decision point. Blocks up to
        `timeout_s` waiting for `submit_decision` to be called via MCP; on
        timeout, logs loudly to stderr and returns `fallback()` instead so
        the simulation can never hang past `timeout_s` (§6 trap #4). Returns
        the (heating_c, cooling_c) tuple to hand to `guardrails.validate` --
        this function never applies guardrails itself, that stays the sim
        thread's job either way.
        """
        pending = PendingDecision(snapshot=snapshot)
        with self._lock:
            self._pending = pending
        try:
            try:
                decision = pending.reply_queue.get(timeout=self.timeout_s)
            except queue.Empty:
                self.timeout_count += 1
                print(
                    f"[decision_handshake] TIMEOUT after {self.timeout_s}s waiting for an MCP "
                    f"decision at sim time {snapshot.get('timestamp')} -- falling back to the "
                    f"rule-based controller. (timeout #{self.timeout_count})",
                    file=sys.stderr,
                    flush=True,
                )
                decision = fallback()
            with self._lock:
                self._result_target = pending
            return decision
        finally:
            with self._lock:
                if self._pending is pending:
                    self._pending = None

    def submit_decision(self, heating_c: float, cooling_c: float) -> PendingDecision | None:
        """Called from the `set_zone_setpoints` MCP tool handler. Returns the
        `PendingDecision` (so the caller can wait on its `result_queue` for
        the guardrail-applied values) or None if no decision is currently
        pending -- e.g. the client called the write-tool outside a decision
        window, or the timeout already fired."""
        with self._lock:
            pending = self._pending
        if pending is None:
            return None
        pending.reply_queue.put((heating_c, cooling_c))
        return pending

    def publish_result(self, entry: dict) -> None:
        """Called (via `SimulationRunner`'s `on_decision` hook) right after a
        decision -- MCP-submitted or fallback -- has been guardrail-validated,
        written to the actuators, and logged. Delivers the applied result
        back to whichever `set_zone_setpoints` call is waiting on it."""
        with self._lock:
            pending = self._result_target
            self._result_target = None
        if pending is not None:
            pending.result_queue.put(entry)
