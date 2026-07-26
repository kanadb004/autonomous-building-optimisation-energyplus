"""Phase 2 validation plot: one representative day, rule-based run --
zone temperature vs. heating/cooling setpoints, showing the setpoints step
when occupancy changes and the zone temperature visibly follows (§2
validation: "setpoint changes visibly take effect in the temperature
traces")."""

import csv
import sys
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
csv_path = REPO_ROOT / "runs" / "phase2_validation" / "rulebased" / "telemetry.csv"

rows = list(csv.DictReader(open(csv_path)))
day_rows = [r for r in rows if r["timestamp"].startswith("1986-01-15")]

times = [datetime.fromisoformat(r["timestamp"]) for r in day_rows]
heat_sp = [float(r["heating_setpoint_c"]) for r in day_rows]
cool_sp = [float(r["cooling_setpoint_c"]) for r in day_rows]
zone_temp = [float(r["zone_temp_c_SPACE1-1"]) for r in day_rows]
occupants = [float(r["zone_occupant_count_SPACE1-1"]) for r in day_rows]

fig, ax = plt.subplots(figsize=(14, 6))
ax.plot(times, zone_temp, label="SPACE1-1 zone temp", color="tab:blue", linewidth=1.5)
ax.step(times, heat_sp, where="post", label="heating setpoint (applied)", color="tab:red", linewidth=1.2)
ax.step(times, cool_sp, where="post", label="cooling setpoint (applied)", color="tab:cyan", linewidth=1.2)
ax.fill_between(times, 20.0, 26.0, alpha=0.08, color="green", label="occupied comfort band [20, 26] C")

occ_ax = ax.twinx()
occ_ax.fill_between(times, occupants, alpha=0.08, color="gray", step="post")
occ_ax.set_ylabel("occupant count (SPACE1-1)")
occ_ax.set_ylim(0, max(occupants) * 4 if max(occupants) else 1)

ax.set_xlabel("Simulation time (1/15, rule-based run)")
ax.set_ylabel("Temperature (C)")
ax.set_title("Phase 2 validation: rule-based setpoint steps vs. zone temperature response (SPACE1-1)")
ax.xaxis.set_major_formatter(mdates.DateFormatter("%Hh"))
ax.legend(loc="upper left", fontsize=8)
fig.autofmt_xdate()
fig.tight_layout()

out_path = REPO_ROOT / "runs" / "phase2_validation" / "setpoint_steps.png"
fig.savefig(out_path, dpi=120)
print(f"saved -> {out_path}")
