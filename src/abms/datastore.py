"""Thread-safe store shared between the sim thread and the tool handlers.

Everything goes through one lock, and callers get copies rather than
references, so a tool handler can't mutate shared state by accident.
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
        """Called once per zone timestep."""
        with self._lock:
            self._latest = record
            self._history.append(record)
            self._prune_locked(record["timestamp"])

    def _prune_locked(self, latest_ts_iso: str) -> None:
        cutoff = datetime.fromisoformat(latest_ts_iso) - self._history_window
        while self._history and datetime.fromisoformat(self._history[0]["timestamp"]) < cutoff:
            self._history.popleft()

    def record_decision(self, entry: dict) -> None:
        """Called once per decision. Separate from update because
        decisions are far rarer than timesteps."""
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
