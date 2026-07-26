"""CSV telemetry logging with a frozen schema (§2 repo structure, §3).

One row per non-warmup, non-sizing zone timestep. This schema is the
dashboard's input (Phase 5) -- do not change column names without updating
every reader.
"""

import csv
from pathlib import Path

ZONE_NAMES = ["SPACE1-1", "SPACE2-1", "SPACE3-1", "SPACE4-1", "SPACE5-1"]

FIELDNAMES = (
    ["timestamp", "run_id", "mode"]
    + [f"zone_temp_c_{z}" for z in ZONE_NAMES]
    + [f"zone_occupant_count_{z}" for z in ZONE_NAMES]
    + [
        "outdoor_temp_c",
        "heating_setpoint_c",
        "cooling_setpoint_c",
        "hvac_electricity_interval_kwh",
        "hvac_electricity_cumulative_kwh",
    ]
)


class TelemetryLogger:
    """Appends one CSV row per call to `append`. Flushes every row so a
    mid-run crash never loses more than the in-flight record."""

    def __init__(self, csv_path: Path):
        self.csv_path = Path(csv_path)
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.csv_path, "w", newline="")
        self._writer = csv.DictWriter(self._file, fieldnames=FIELDNAMES)
        self._writer.writeheader()
        self._file.flush()

    def append(self, record: dict) -> None:
        self._writer.writerow(record)
        self._file.flush()

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()
