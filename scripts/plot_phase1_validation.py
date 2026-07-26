"""Plots a week of zone temperature against outdoor temperature."""

import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.dates as mdates  # noqa: E402
from datetime import datetime  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
csv_path = REPO_ROOT / "runs" / "phase1_validation" / "telemetry.csv"

rows = list(csv.DictReader(open(csv_path)))
times = [datetime.fromisoformat(r["timestamp"]) for r in rows]
outdoor = [float(r["outdoor_temp_c"]) for r in rows]
zone_cols = [c for c in rows[0] if c.startswith("zone_temp_c_")]

fig, ax = plt.subplots(figsize=(14, 6))
for col in zone_cols:
    ax.plot(times, [float(r[col]) for r in rows], label=col.replace("zone_temp_c_", ""), linewidth=1)
ax.plot(times, outdoor, label="outdoor", color="black", linewidth=1.5, linestyle="--")
ax.axhline(16.7, color="gray", linewidth=0.5, linestyle=":")
ax.axhline(29.4, color="gray", linewidth=0.5, linestyle=":")
ax.set_xlabel("Simulation time")
ax.set_ylabel("Temperature (C)")
ax.set_title("Phase 1 validation: zone vs outdoor temperature, 1/14-1/20 (5ZoneAirCooled, Chicago)")
ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %Hh"))
ax.legend(loc="upper right", fontsize=8)
fig.autofmt_xdate()
fig.tight_layout()

out_path = REPO_ROOT / "runs" / "phase1_validation" / "zone_vs_outdoor_temp.png"
fig.savefig(out_path, dpi=120)
print(f"saved -> {out_path}")
