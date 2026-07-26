"""Recompute summary.json for each committed period from its telemetry.

Nothing is simulated here; this just picks up metrics added since the runs
were made. Existing fields must come out unchanged, so the script prints a
field-level diff before overwriting and a regression shows up here rather
than in a commit.

    PYTHONPATH=src python scripts/regenerate_summaries.py
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from abms import config, metrics  # noqa: E402

DEMO_ROOT = REPO_ROOT / "runs" / "demo_final"


def _flatten(d: dict, prefix: str = "") -> dict:
    """Flattens nested dicts to dotted keys so scalar-level diffs are easy
    to print, e.g. {"baseline": {"total_hvac_kwh": 1.0}} ->
    {"baseline.total_hvac_kwh": 1.0}."""
    out = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def diff_summaries(old: dict, new: dict) -> tuple:
    """Returns (changed, added, removed) lists of (key, old_val, new_val)
    or (key, val) tuples. `changed` on a pre-existing field is the
    regression this script exists to catch."""
    old_flat = _flatten(old)
    new_flat = _flatten(new)
    changed = [
        (k, old_flat[k], new_flat[k])
        for k in old_flat
        if k in new_flat and old_flat[k] != new_flat[k]
    ]
    added = [(k, new_flat[k]) for k in new_flat if k not in old_flat]
    removed = [(k, old_flat[k]) for k in old_flat if k not in new_flat]
    return changed, added, removed


def regenerate_period(period_dir: Path, peak_demand_kw_threshold: float) -> bool:
    """Regenerates one period's summary.json. Returns True if any
    pre-existing field changed value (a regression)."""
    baseline_dir = period_dir / "baseline"
    ai_dir = period_dir / "ai"
    rulebased_dir = period_dir / "rulebased"
    if not (baseline_dir / "telemetry.csv").exists() or not (ai_dir / "telemetry.csv").exists():
        print(f"[regenerate_summaries] {period_dir.name}: missing baseline/ai telemetry, skipping")
        return False

    summary_path = period_dir / "summary.json"
    old_summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}

    if (rulebased_dir / "telemetry.csv").exists():
        new_summary = metrics.compare_three(
            baseline_dir, rulebased_dir, ai_dir, peak_demand_kw_threshold=peak_demand_kw_threshold
        )
    else:
        new_summary = metrics.compare_runs(
            baseline_dir, ai_dir, peak_demand_kw_threshold=peak_demand_kw_threshold
        )
        new_summary = {"baseline": new_summary["baseline"], "ai": new_summary["controlled"],
                        "comparison": {"ai_vs_baseline": new_summary["comparison"]}}

    changed, added, removed = diff_summaries(old_summary, new_summary)

    print(f"\n[regenerate_summaries] {period_dir.name}")
    if not old_summary:
        print("  (no prior summary.json -- nothing to diff)")
    else:
        print(f"  {len(changed)} changed, {len(added)} added, {len(removed)} removed")
        for k, old_v, new_v in changed:
            print(f"  CHANGED  {k}: {old_v!r} -> {new_v!r}")
        for k, new_v in added:
            print(f"  added    {k}: {new_v!r}")
        for k, old_v in removed:
            print(f"  removed  {k}: {old_v!r}")

    metrics.write_summary(new_summary, summary_path)
    return len(changed) > 0


def main() -> int:
    cfg = config.load()
    threshold = cfg.get("peak_demand_kw_threshold")

    period_dirs = sorted(
        d for d in DEMO_ROOT.iterdir()
        if d.is_dir() and (d / "baseline" / "telemetry.csv").exists()
    ) if DEMO_ROOT.exists() else []

    if not period_dirs:
        print(f"[regenerate_summaries] no period dirs with baseline/telemetry.csv under {DEMO_ROOT}")
        return 1

    any_regression = False
    for period_dir in period_dirs:
        if regenerate_period(period_dir, threshold):
            any_regression = True

    if any_regression:
        print("\n[regenerate_summaries] REGRESSION: a pre-existing field changed value. "
              "See CHANGED lines above -- do not commit until explained.")
        return 1
    print("\n[regenerate_summaries] OK -- no pre-existing field changed value.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
