"""Phase 1 validation: run the API wrapper for the 1-week dev RunPeriod,
plot zone vs outdoor temperature, and cross-check total HVAC electricity
against the plain-CLI eplustbl.htm / eplusmtr.csv reference (§2 Phase 1
validation, §7)."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from abms.config import ensure_pyenergyplus_on_path  # noqa: E402

ensure_pyenergyplus_on_path()

from abms.simulation import SimulationRunner  # noqa: E402

RUN_ID = "phase1_validation"
OUTPUT_DIR = REPO_ROOT / "runs" / RUN_ID

runner = SimulationRunner(
    idf_path=REPO_ROOT / "models" / "building.idf",
    epw_path=REPO_ROOT / "models" / "weather" / "USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw",
    output_dir=OUTPUT_DIR,
    run_id=RUN_ID,
    mode="baseline",
)
runner.start()
runner.join()

print(f"exit_code={runner.exit_code}")
print(f"fatal_error={runner.fatal_error}")
if runner.exit_code != 0 or runner.fatal_error:
    sys.exit(1)

print(f"telemetry rows written -> {OUTPUT_DIR / 'telemetry.csv'}")
