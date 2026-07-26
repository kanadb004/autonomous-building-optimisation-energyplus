"""Energy/comfort/carbon comparison + summary.json writer (§2.5).

Reads two telemetry CSVs (baseline, controlled) produced by
`SimulationRunner`, computes total HVAC energy, occupied-hours comfort-band
compliance, and carbon accounting, and writes a comparison summary.
"""

import csv
import json
from pathlib import Path

from abms.carbon import gas_kwh_to_kg_co2, kwh_to_kg_co2
from abms.guardrails import OCCUPIED_COOL_CEILING_C, OCCUPIED_HEAT_FLOOR_C
from abms.telemetry import ZONE_NAMES


def load_telemetry(csv_path) -> list:
    with open(csv_path, newline="") as f:
        return list(csv.DictReader(f))


def total_electricity_kwh(rows: list) -> float:
    return sum(float(r["hvac_electricity_interval_kwh"]) for r in rows)


def total_gas_kwh(rows: list) -> float:
    return sum(float(r["hvac_gas_interval_kwh"]) for r in rows)


def total_hvac_kwh(rows: list) -> float:
    """Total site HVAC energy (electricity + gas, both in kWh). A
    setpoint-only setback strategy mostly saves gas (reheat coil) in a
    heating-dominated period -- electricity alone understates it (§ Phase 2
    energy-metric broadening, docs/decisions.md)."""
    return total_electricity_kwh(rows) + total_gas_kwh(rows)


def total_carbon_kg(rows: list) -> float:
    total = 0.0
    for r in rows:
        hour = int(r["timestamp"][11:13])
        total += kwh_to_kg_co2(float(r["hvac_electricity_interval_kwh"]), hour)
        total += gas_kwh_to_kg_co2(float(r["hvac_gas_interval_kwh"]))
    return total


def comfort_compliance_pct(rows: list) -> float:
    """% of occupied zone-timesteps where that zone's temperature is within
    [OCCUPIED_HEAT_FLOOR_C, OCCUPIED_COOL_CEILING_C]. A zone-timestep counts
    as "occupied" only for the zone(s) actually occupied at that time, not
    building-wide, since the schedules are shared but occupancy is per-zone."""
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


def summarize_run(run_dir) -> dict:
    rows = load_telemetry(Path(run_dir) / "telemetry.csv")
    return {
        "run_id": rows[0]["run_id"] if rows else None,
        "mode": rows[0]["mode"] if rows else None,
        "total_hvac_kwh": total_hvac_kwh(rows),
        "total_electricity_kwh": total_electricity_kwh(rows),
        "total_gas_kwh": total_gas_kwh(rows),
        "carbon_kg": total_carbon_kg(rows),
        "comfort_compliance_pct": comfort_compliance_pct(rows),
        "zone_timesteps": len(rows),
    }


def compare_runs(baseline_dir, controlled_dir) -> dict:
    baseline = summarize_run(baseline_dir)
    controlled = summarize_run(controlled_dir)

    energy_saved_kwh = baseline["total_hvac_kwh"] - controlled["total_hvac_kwh"]
    energy_saved_pct = (
        100.0 * energy_saved_kwh / baseline["total_hvac_kwh"] if baseline["total_hvac_kwh"] else 0.0
    )
    carbon_avoided_kg = baseline["carbon_kg"] - controlled["carbon_kg"]
    carbon_avoided_pct = (
        100.0 * carbon_avoided_kg / baseline["carbon_kg"] if baseline["carbon_kg"] else 0.0
    )

    return {
        "baseline": baseline,
        "controlled": controlled,
        "comparison": {
            "energy_saved_kwh": energy_saved_kwh,
            "energy_saved_pct": energy_saved_pct,
            "carbon_avoided_kg": carbon_avoided_kg,
            "carbon_avoided_pct": carbon_avoided_pct,
            "comfort_compliance_delta_pct": controlled["comfort_compliance_pct"] - baseline["comfort_compliance_pct"],
        },
    }


def write_summary(summary: dict, output_path) -> None:
    Path(output_path).write_text(json.dumps(summary, indent=2))
