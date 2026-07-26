"""Smoke check: import pyenergyplus from the EnergyPlus install and run a
trivial model through the API. Re-run after any environment change."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from abms.config import ensure_pyenergyplus_on_path  # noqa: E402

ep_dir = ensure_pyenergyplus_on_path()

from pyenergyplus.api import EnergyPlusAPI  # noqa: E402

api = EnergyPlusAPI()
print(f"EnergyPlus API version: {api.api_version()}")

idf = ep_dir / "ExampleFiles" / "1ZoneUncontrolled.idf"
epw = ep_dir / "WeatherData" / "USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw"
out_dir = Path(__file__).resolve().parents[1] / "runs" / "_smoke_test"
out_dir.mkdir(parents=True, exist_ok=True)

state = api.state_manager.new_state()
exit_code = api.runtime.run_energyplus(
    state,
    [
        "-w", str(epw),
        "-d", str(out_dir),
        "-r",
        str(idf),
    ],
)
api.state_manager.delete_state(state)

print(f"EnergyPlus run exit code: {exit_code}")
if exit_code != 0:
    sys.exit(exit_code)
print("SMOKE CHECK PASSED: pyenergyplus import + API run succeeded.")
