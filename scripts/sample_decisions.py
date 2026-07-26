"""Phase 4 validation (§7 "decision-log audit"): sample N random decisions
from an AI run's decisions.jsonl and pair each with the telemetry state at
that timestamp, so a human can check every decision is justified by what
the model actually saw (§4's "Validation before Phase 5 sign-off").
"""

import argparse
import csv
import json
import random
from pathlib import Path


def load_decisions(path: Path) -> list:
    with open(path) as f:
        return [json.loads(line) for line in f]


def load_telemetry_by_timestamp(path: Path) -> dict:
    with open(path, newline="") as f:
        return {row["timestamp"]: row for row in csv.DictReader(f)}


def zone_summary(row: dict) -> dict:
    zones = sorted({k.rsplit("_", 1)[-1] for k in row if k.startswith("zone_temp_c_")})
    return {
        z: {
            "temp_c": round(float(row[f"zone_temp_c_{z}"]), 2),
            "occupants": round(float(row[f"zone_occupant_count_{z}"]), 1),
        }
        for z in zones
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", help="Directory containing decisions.jsonl and telemetry.csv (an AI run)")
    parser.add_argument("-n", "--count", type=int, default=20)
    parser.add_argument("--seed", type=int, default=None, help="Omit for a fresh random sample each run.")
    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir)
    decisions = load_decisions(run_dir / "decisions.jsonl")
    telemetry_by_ts = load_telemetry_by_timestamp(run_dir / "telemetry.csv")

    rng = random.Random(args.seed)
    sample = rng.sample(decisions, min(args.count, len(decisions)))
    sample.sort(key=lambda d: d["timestamp"])

    for i, d in enumerate(sample, 1):
        row = telemetry_by_ts.get(d["timestamp"])
        print(f"\n--- decision {i}/{len(sample)}: {d['timestamp']} ({d['controller']}) ---")
        if row is not None:
            print(f"  outdoor_temp_c: {round(float(row['outdoor_temp_c']), 2)}")
            print(f"  zones: {json.dumps(zone_summary(row))}")
        else:
            print("  (no exact telemetry row at this timestamp)")
        print(f"  occupied: {d['occupied']}")
        print(f"  requested: {d['requested']}")
        print(f"  applied:   {d['applied']}")
        if d["guardrail_notes"]:
            print(f"  guardrail_notes: {d['guardrail_notes']}")
        print(f"  reasoning: {d['reasoning']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
