"""CLI entry point.

compare runs baseline then rule-based. compare-ai adds the AI run for a
three-way comparison. demo repeats compare-ai for each period listed in
config/default.yaml, patching the IDF's RunPeriod for each one instead of
keeping a committed IDF per period.

Every mode writes telemetry under runs/<run_id>/ plus a summary.json.
"""

import argparse
import asyncio
import datetime
import hashlib
import json
import sys
from pathlib import Path

from abms import config

config.ensure_pyenergyplus_on_path()

from abms import agent_runner, idf_utils, metrics  # noqa: E402
from abms.controllers.baseline import BaselineController  # noqa: E402
from abms.controllers.rulebased import RuleBasedController  # noqa: E402
from abms.simulation import SimulationRunner  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_IDF = REPO_ROOT / "models" / "building.idf"
DEFAULT_EPW = REPO_ROOT / "models" / "weather" / "USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw"
DECISION_INTERVAL_MINUTES = 15
# Length of the committed IDF's own RunPeriod, 1/14 to 1/20.
DEFAULT_PERIOD_DAYS = 7.0


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


def run_ai(
    output_dir: Path,
    run_id: str,
    period_days: float = DEFAULT_PERIOD_DAYS,
    idf_path=DEFAULT_IDF,
    epw_path=DEFAULT_EPW,
    decision_interval_minutes: int | None = None,
    timeout_s: float = 60.0,
) -> Path:
    """Run the AI-controlled simulation and return its telemetry dir.

    Same <output_dir>/<mode> shape run_single uses, so compare_three can
    treat all three the same way.
    """
    cfg = config.load()
    interval = decision_interval_minutes or cfg["decision_interval_minutes"]["llm"]
    llm_agent, history_hours, _mode = agent_runner.build_llm_agent()
    max_decisions = agent_runner.expected_decision_count(period_days, interval) + 2
    run_dir = output_dir / "ai"
    asyncio.run(
        agent_runner.run_agent_session(
            idf_path=idf_path,
            epw_path=epw_path,
            output_dir=run_dir,
            run_id=run_id,
            decision_interval_minutes=interval,
            timeout_s=timeout_s,
            max_decisions=max_decisions,
            llm_agent=llm_agent,
            history_hours=history_hours,
        )
    )
    return run_dir


def run_compare(output_dir: Path, run_id: str, idf_path=DEFAULT_IDF, epw_path=DEFAULT_EPW) -> dict:
    baseline_dir = run_single("baseline", output_dir, run_id, idf_path, epw_path)
    rulebased_dir = run_single("rulebased", output_dir, run_id, idf_path, epw_path)
    summary = metrics.compare_runs(baseline_dir, rulebased_dir)
    metrics.write_summary(summary, output_dir / "summary.json")
    return summary


def run_full_comparison(
    output_dir: Path, run_id: str, period_days: float = DEFAULT_PERIOD_DAYS, idf_path=DEFAULT_IDF, epw_path=DEFAULT_EPW
) -> dict:
    """Baseline vs rule-based vs AI over the same period and weather."""
    baseline_dir = run_single("baseline", output_dir, run_id, idf_path, epw_path)
    rulebased_dir = run_single("rulebased", output_dir, run_id, idf_path, epw_path)
    ai_dir = run_ai(output_dir, run_id, period_days, idf_path, epw_path)
    summary = metrics.compare_three(baseline_dir, rulebased_dir, ai_dir)
    metrics.write_summary(summary, output_dir / "summary.json")
    return summary


def _write_manifest(period_dir: Path, source_idf_path: Path, patched_idf_path: Path) -> None:
    """Record the source model path and its hash next to the patched IDF,
    so a run directory describes itself."""
    source_hash = hashlib.sha256(source_idf_path.read_bytes()).hexdigest()
    manifest = {
        "source_idf": str(source_idf_path.relative_to(REPO_ROOT)),
        "source_idf_sha256": source_hash,
        "patched_idf": patched_idf_path.name,
    }
    (period_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def _period_days(period: dict) -> float:
    # Any non-leap year will do; only the day count matters here.
    start = datetime.date(2001, period["begin_month"], period["begin_day"])
    end = datetime.date(2001, period["end_month"], period["end_day"])
    return (end - start).days + 1


def run_demo(output_dir: Path, run_id: str) -> dict:
    """Run a full three-way comparison for each configured demo period.

    Each lands under <output_dir>/<label>/, with a combined summary.json
    keyed by label.
    """
    cfg = config.load()
    building_idf = REPO_ROOT / cfg["building_idf"]
    weather_file = REPO_ROOT / cfg["weather_file"]

    results = {}
    for period in cfg["demo_periods"]:
        label = period["label"]
        period_dir = output_dir / label
        patched_idf = period_dir / "building.idf"
        idf_utils.with_run_period(
            building_idf,
            period["begin_month"],
            period["begin_day"],
            period["end_month"],
            period["end_day"],
            patched_idf,
        )
        _write_manifest(period_dir, building_idf, patched_idf)
        results[label] = run_full_comparison(
            period_dir, f"{run_id}_{label}", _period_days(period), patched_idf, weather_file
        )
    metrics.write_summary(results, output_dir / "summary.json")
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["baseline", "rulebased", "ai", "compare", "compare-ai", "demo"])
    parser.add_argument("--run-id", default="phase2")
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "runs"))
    parser.add_argument(
        "--period-days",
        type=float,
        default=DEFAULT_PERIOD_DAYS,
        help="Sim days in the IDF's RunPeriod (ai and compare-ai only).",
    )
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir) / args.run_id

    if args.mode == "compare":
        summary = run_compare(output_dir, args.run_id)
        print(f"energy_saved_pct: {summary['comparison']['energy_saved_pct']:.2f}")
        print(f"comfort_compliance_pct (baseline): {summary['baseline']['comfort_compliance_pct']:.2f}")
        print(f"comfort_compliance_pct (rulebased): {summary['controlled']['comfort_compliance_pct']:.2f}")
        print(f"carbon_avoided_kg: {summary['comparison']['carbon_avoided_kg']:.4f}")
    elif args.mode == "compare-ai":
        summary = run_full_comparison(output_dir, args.run_id, args.period_days)
        for key in ("rulebased_vs_baseline", "ai_vs_baseline"):
            c = summary["comparison"][key]
            print(f"{key}: energy_saved_pct={c['energy_saved_pct']:.2f} carbon_avoided_kg={c['carbon_avoided_kg']:.4f}")
    elif args.mode == "demo":
        results = run_demo(output_dir, args.run_id)
        for label, summary in results.items():
            c = summary["comparison"]["ai_vs_baseline"]
            print(f"{label}: ai energy_saved_pct={c['energy_saved_pct']:.2f} carbon_avoided_kg={c['carbon_avoided_kg']:.4f}")
    elif args.mode == "ai":
        run_dir = run_ai(output_dir, args.run_id, args.period_days)
        print(f"wrote telemetry to {run_dir}")
    else:
        run_dir = run_single(args.mode, output_dir, args.run_id)
        print(f"wrote telemetry to {run_dir}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
