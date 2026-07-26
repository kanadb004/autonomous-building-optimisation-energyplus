"""CLI entry: run baseline / rulebased / compare (§2.5).

`compare` runs baseline then rule-based with identical IDF/EPW/period,
writing both telemetry sets under `runs/<run_id>/{baseline,rulebased}/` and
a `summary.json` with the energy/comfort/carbon comparison.
"""

import argparse
import sys
from pathlib import Path

from abms import config

config.ensure_pyenergyplus_on_path()

from abms import metrics  # noqa: E402
from abms.controllers.baseline import BaselineController  # noqa: E402
from abms.controllers.rulebased import RuleBasedController  # noqa: E402
from abms.simulation import SimulationRunner  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_IDF = REPO_ROOT / "models" / "building.idf"
DEFAULT_EPW = REPO_ROOT / "models" / "weather" / "USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw"
DECISION_INTERVAL_MINUTES = 15


def run_single(mode: str, output_dir: Path, run_id: str, idf_path=DEFAULT_IDF, epw_path=DEFAULT_EPW) -> Path:
    controller = BaselineController() if mode == "baseline" else RuleBasedController()
    run_dir = output_dir / mode
    runner = SimulationRunner(
        idf_path=idf_path,
        epw_path=epw_path,
        output_dir=run_dir,
        run_id=run_id,
        mode=mode,
        controller=controller,
        decision_interval_minutes=DECISION_INTERVAL_MINUTES,
    )
    runner.start()
    runner.join()
    if runner.fatal_error:
        raise RuntimeError(f"Simulation ({mode}) failed:\n{runner.fatal_error}")
    return run_dir


def run_compare(output_dir: Path, run_id: str, idf_path=DEFAULT_IDF, epw_path=DEFAULT_EPW) -> dict:
    baseline_dir = run_single("baseline", output_dir, run_id, idf_path, epw_path)
    rulebased_dir = run_single("rulebased", output_dir, run_id, idf_path, epw_path)
    summary = metrics.compare_runs(baseline_dir, rulebased_dir)
    metrics.write_summary(summary, output_dir / "summary.json")
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["baseline", "rulebased", "compare"])
    parser.add_argument("--run-id", default="phase2")
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "runs"))
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir) / args.run_id

    if args.mode == "compare":
        summary = run_compare(output_dir, args.run_id)
        print(f"energy_saved_pct: {summary['comparison']['energy_saved_pct']:.2f}")
        print(f"comfort_compliance_pct (baseline): {summary['baseline']['comfort_compliance_pct']:.2f}")
        print(f"comfort_compliance_pct (rulebased): {summary['controlled']['comfort_compliance_pct']:.2f}")
        print(f"carbon_avoided_kg: {summary['comparison']['carbon_avoided_kg']:.4f}")
    else:
        run_dir = run_single(args.mode, output_dir, args.run_id)
        print(f"wrote telemetry to {run_dir}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
