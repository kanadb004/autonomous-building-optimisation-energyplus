"""Actuation wiring check: force an absurd cooling setpoint for a day,
guardrails bypassed on purpose, and confirm the zone temperature responds.

Proves the actuator drives the schedule the thermostat really reads, and
not a similarly named decoy.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from abms.config import ensure_pyenergyplus_on_path  # noqa: E402

ensure_pyenergyplus_on_path()

from abms.controllers.base import Controller  # noqa: E402
from abms.idf_utils import with_run_period  # noqa: E402
from abms.simulation import SimulationRunner  # noqa: E402


class AbsurdCoolingController(Controller):
    """Constantly demands an absurdly cold cooling setpoint, unclamped."""

    name = "absurd_cooling_sanity_check"
    actuates = True
    bypass_guardrails = True

    def decide(self, snapshot: dict):
        return (12.0, 15.0)  # heating low (out of the way), cooling absurdly cold


RUN_ID = "phase2_actuation_sanity_check"
OUTPUT_DIR = REPO_ROOT / "runs" / RUN_ID
idf_path = with_run_period(
    REPO_ROOT / "models" / "building.idf", 1, 14, 1, 14, OUTPUT_DIR / "building_one_day.idf"
)

runner = SimulationRunner(
    idf_path=idf_path,
    epw_path=REPO_ROOT / "models" / "weather" / "USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw",
    output_dir=OUTPUT_DIR,
    run_id=RUN_ID,
    mode="absurd_cooling_sanity_check",
    controller=AbsurdCoolingController(),
    decision_interval_minutes=15,
)
runner.start()
runner.join()

print(f"exit_code={runner.exit_code}")
print(f"fatal_error={runner.fatal_error}")
if runner.exit_code != 0 or runner.fatal_error:
    sys.exit(1)

import csv  # noqa: E402

rows = list(csv.DictReader(open(OUTPUT_DIR / "telemetry.csv")))
zone_cols = [c for c in rows[0] if c.startswith("zone_temp_c_")]
min_temps = {c: min(float(r[c]) for r in rows) for c in zone_cols}
print("Minimum zone temperatures with 15C absurd cooling setpoint forced all day:")
for c, v in min_temps.items():
    print(f"  {c}: {v:.2f} C")

if all(v < 20.0 for v in min_temps.values()):
    print("PASS: all zones dropped well below the normal ~21-24C occupied band -- actuator is live.")
else:
    print("FAIL: zone temperatures did not respond to the absurd setpoint -- actuator may be wired wrong.")
    sys.exit(1)
