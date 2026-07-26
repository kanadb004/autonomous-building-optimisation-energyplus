"""Energy, comfort and carbon comparison, and the summary.json writer.

Reads the telemetry CSVs written by SimulationRunner and compares them.
"""

import csv
import json
from datetime import datetime
from pathlib import Path

from abms.carbon import gas_kwh_to_kg_co2, kwh_to_kg_co2
from abms.comfort import pmv_for_zone
from abms.guardrails import OCCUPIED_COOL_CEILING_C, OCCUPIED_HEAT_FLOOR_C
from abms.telemetry import ZONE_NAMES

# ASHRAE 55: |PMV| at or below this counts as comfortable.
PMV_COMFORT_THRESHOLD = 0.5

# Used when there are too few rows to derive the interval from timestamps.
# Matches this model's Timestep,4.
DEFAULT_INTERVAL_MINUTES = 15.0


def load_telemetry(csv_path) -> list:
    with open(csv_path, newline="") as f:
        return list(csv.DictReader(f))


def interval_minutes(rows: list) -> float:
    """Timestep length from the first two timestamps. Falls back to the
    default if there aren't enough rows, and says so."""
    if len(rows) < 2:
        print(f"[metrics] interval_minutes: {len(rows)} row(s), defaulting to {DEFAULT_INTERVAL_MINUTES} min")
        return DEFAULT_INTERVAL_MINUTES
    t0 = datetime.fromisoformat(rows[0]["timestamp"])
    t1 = datetime.fromisoformat(rows[1]["timestamp"])
    delta = (t1 - t0).total_seconds() / 60.0
    if delta <= 0:
        print(f"[metrics] interval_minutes: non-positive delta ({delta}), defaulting to {DEFAULT_INTERVAL_MINUTES} min")
        return DEFAULT_INTERVAL_MINUTES
    return delta


def interval_kwh_to_kw(interval_kwh: float, interval_min: float) -> float:
    """Average kW implied by an interval kWh reading. Everything that deals
    in peak demand goes through here."""
    return float(interval_kwh) * 60.0 / interval_min


def total_electricity_kwh(rows: list) -> float:
    return sum(float(r["hvac_electricity_interval_kwh"]) for r in rows)


def total_gas_kwh(rows: list) -> float:
    return sum(float(r["hvac_gas_interval_kwh"]) for r in rows)


def total_hvac_kwh(rows: list) -> float:
    """Electricity plus gas. Setback mostly saves gas in winter, so
    electricity alone understates the saving."""
    return total_electricity_kwh(rows) + total_gas_kwh(rows)


def total_carbon_kg(rows: list) -> float:
    total = 0.0
    for r in rows:
        hour = int(r["timestamp"][11:13])
        total += kwh_to_kg_co2(float(r["hvac_electricity_interval_kwh"]), hour)
        total += gas_kwh_to_kg_co2(float(r["hvac_gas_interval_kwh"]))
    return total


def comfort_compliance_pct(rows: list) -> float:
    """Percent of occupied zone-timesteps inside the comfort band.

    Occupancy is counted per zone, not building-wide.
    """
    occupied_count = 0
    compliant_count = 0
    for r in rows:
        for zone in ZONE_NAMES:
            occupants = float(r[f"zone_occupant_count_{zone}"])
            if occupants <= 0:
                continue
            occupied_count += 1
            temp = float(r[f"zone_temp_c_{zone}"])
            if OCCUPIED_HEAT_FLOOR_C <= temp <= OCCUPIED_COOL_CEILING_C:
                compliant_count += 1
    if occupied_count == 0:
        return 100.0
    return 100.0 * compliant_count / occupied_count


def pmv_stats(rows: list) -> dict:
    """PMV mean, mean absolute, and percent within band, over occupied
    zone-timesteps only."""
    occupied_count = 0
    pmv_sum = 0.0
    pmv_abs_sum = 0.0
    within_count = 0
    for r in rows:
        month = int(r["timestamp"][5:7])
        for zone in ZONE_NAMES:
            occupants = float(r[f"zone_occupant_count_{zone}"])
            if occupants <= 0:
                continue
            occupied_count += 1
            temp = float(r[f"zone_temp_c_{zone}"])
            value = pmv_for_zone(temp, month)
            pmv_sum += value
            pmv_abs_sum += abs(value)
            if abs(value) <= PMV_COMFORT_THRESHOLD:
                within_count += 1
    if occupied_count == 0:
        return {"pmv_mean": 0.0, "pmv_mean_abs": 0.0, "pmv_within_pct": 100.0}
    return {
        "pmv_mean": pmv_sum / occupied_count,
        "pmv_mean_abs": pmv_abs_sum / occupied_count,
        "pmv_within_pct": 100.0 * within_count / occupied_count,
    }


def peak_demand_kw(rows: list, interval_min: float | None = None) -> tuple:
    """Peak interval-average kW and when it happened."""
    if not rows:
        return 0.0, None
    im = interval_min if interval_min is not None else interval_minutes(rows)
    best_kw, best_ts = float("-inf"), None
    for r in rows:
        kw = interval_kwh_to_kw(r["hvac_electricity_interval_kwh"], im)
        if kw > best_kw:
            best_kw, best_ts = kw, r["timestamp"]
    return best_kw, best_ts


def pct_intervals_above_threshold(rows: list, threshold_kw: float, interval_min: float | None = None) -> float:
    """Percent of timesteps whose average kW exceeds threshold_kw."""
    if not rows:
        return 0.0
    im = interval_min if interval_min is not None else interval_minutes(rows)
    above = sum(1 for r in rows if interval_kwh_to_kw(r["hvac_electricity_interval_kwh"], im) > threshold_kw)
    return 100.0 * above / len(rows)


def summarize_run(run_dir, peak_demand_kw_threshold: float | None = None) -> dict:
    rows = load_telemetry(Path(run_dir) / "telemetry.csv")
    im = interval_minutes(rows) if rows else DEFAULT_INTERVAL_MINUTES
    peak_kw, peak_at = peak_demand_kw(rows, im)
    summary = {
        "run_id": rows[0]["run_id"] if rows else None,
        "mode": rows[0]["mode"] if rows else None,
        "total_hvac_kwh": total_hvac_kwh(rows),
        "total_electricity_kwh": total_electricity_kwh(rows),
        "total_gas_kwh": total_gas_kwh(rows),
        "carbon_kg": total_carbon_kg(rows),
        "comfort_compliance_pct": comfort_compliance_pct(rows),
        "zone_timesteps": len(rows),
        "peak_demand_kw": peak_kw,
        "peak_demand_at": peak_at,
        **pmv_stats(rows),
    }
    if peak_demand_kw_threshold is not None:
        summary["pct_intervals_above_threshold"] = pct_intervals_above_threshold(
            rows, peak_demand_kw_threshold, im
        )
    return summary


def compare_runs(baseline_dir, controlled_dir, peak_demand_kw_threshold: float | None = None) -> dict:
    baseline = summarize_run(baseline_dir, peak_demand_kw_threshold)
    controlled = summarize_run(controlled_dir, peak_demand_kw_threshold)
    return {
        "baseline": baseline,
        "controlled": controlled,
        "comparison": _comparison(baseline, controlled),
    }


def _comparison(baseline: dict, controlled: dict) -> dict:
    energy_saved_kwh = baseline["total_hvac_kwh"] - controlled["total_hvac_kwh"]
    energy_saved_pct = (
        100.0 * energy_saved_kwh / baseline["total_hvac_kwh"] if baseline["total_hvac_kwh"] else 0.0
    )
    carbon_avoided_kg = baseline["carbon_kg"] - controlled["carbon_kg"]
    carbon_avoided_pct = (
        100.0 * carbon_avoided_kg / baseline["carbon_kg"] if baseline["carbon_kg"] else 0.0
    )
    peak_demand_reduction_kw = baseline["peak_demand_kw"] - controlled["peak_demand_kw"]
    peak_demand_reduction_pct = (
        100.0 * peak_demand_reduction_kw / baseline["peak_demand_kw"] if baseline["peak_demand_kw"] else 0.0
    )
    return {
        "energy_saved_kwh": energy_saved_kwh,
        "energy_saved_pct": energy_saved_pct,
        "carbon_avoided_kg": carbon_avoided_kg,
        "carbon_avoided_pct": carbon_avoided_pct,
        "comfort_compliance_delta_pct": controlled["comfort_compliance_pct"] - baseline["comfort_compliance_pct"],
        "peak_demand_reduction_kw": peak_demand_reduction_kw,
        "peak_demand_reduction_pct": peak_demand_reduction_pct,
        "pmv_within_delta_pct": controlled["pmv_within_pct"] - baseline["pmv_within_pct"],
    }


def compare_three(baseline_dir, rulebased_dir, ai_dir, peak_demand_kw_threshold: float | None = None) -> dict:
    """Baseline vs rule-based vs AI over the same period.

    Reuses the pairwise math from compare_runs so the two summaries can't
    disagree.
    """
    baseline = summarize_run(baseline_dir, peak_demand_kw_threshold)
    rulebased = summarize_run(rulebased_dir, peak_demand_kw_threshold)
    ai = summarize_run(ai_dir, peak_demand_kw_threshold)
    return {
        "baseline": baseline,
        "rulebased": rulebased,
        "ai": ai,
        "comparison": {
            "rulebased_vs_baseline": _comparison(baseline, rulebased),
            "ai_vs_baseline": _comparison(baseline, ai),
        },
    }


def write_summary(summary: dict, output_path) -> None:
    Path(output_path).write_text(json.dumps(summary, indent=2))
