"""CSV telemetry, one row per zone timestep.

The dashboard and the metrics code both read these column names, so don't
rename one without updating them.
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
        # The boiler's gas meter. In winter almost all the setback saving
        # lands here rather than on electricity.
        "hvac_gas_interval_kwh",
        "hvac_gas_cumulative_kwh",
    ]
)


class TelemetryLogger:
    """Appends one row per call. Flushes every row, so a crash loses at
    most the record in flight."""

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
