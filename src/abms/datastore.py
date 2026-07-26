"""Thread-safe shared state store (§3.1): the sim thread pushes every
zone-timestep record here via `SimulationRunner`'s `on_state`/`on_decision`
hooks; MCP tool handlers (running on the asyncio event loop, same process --
see §3 architecture decision) read from it. All access goes through a single
lock; callers get back copies, never references into the store, so a tool
handler can't accidentally mutate shared state.
"""

import threading
from collections import deque
from datetime import datetime, timedelta

HISTORY_WINDOW = timedelta(hours=24)


class SharedState:
    def __init__(self, history_window: timedelta = HISTORY_WINDOW):
        self._lock = threading.Lock()
        self._history_window = history_window
        self._latest = None
        self._history = deque()
        self._decisions_count = 0
        self._last_decision = None

    def update(self, record: dict) -> None:
        """Called once per zone timestep (`on_state`)."""
        with self._lock:
            self._latest = record
            self._history.append(record)
            self._prune_locked(record["timestamp"])

    def _prune_locked(self, latest_ts_iso: str) -> None:
        cutoff = datetime.fromisoformat(latest_ts_iso) - self._history_window
        while self._history and datetime.fromisoformat(self._history[0]["timestamp"]) < cutoff:
            self._history.popleft()

    def record_decision(self, entry: dict) -> None:
        """Called once per decision (`on_decision`) -- separate from
        `update` because decisions happen far less often than zone
        timesteps."""
        with self._lock:
            self._decisions_count += 1
            self._last_decision = entry

    def latest(self) -> dict | None:
        with self._lock:
            return dict(self._latest) if self._latest is not None else None

    def history(self) -> list:
        with self._lock:
            return [dict(r) for r in self._history]

    def decisions_count(self) -> int:
        with self._lock:
            return self._decisions_count

    def last_decision(self) -> dict | None:
        with self._lock:
            return dict(self._last_decision) if self._last_decision is not None else None
