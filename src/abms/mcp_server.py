"""MCP tools, wired to the decision handshake.

The server and the simulation share one process. The sim thread blocks on
a DecisionHandshake at each interval; the tool handlers run on the asyncio
loop serving stdio, read from SharedState, and post decisions back into
that handshake. No IPC, no cross-process timing to get wrong.

The tool docstrings below are what the model reads, so changing them
changes the agent's behaviour.
"""

import argparse
import queue as _queue
import sys
from collections import defaultdict
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from abms import config

config.ensure_pyenergyplus_on_path()

from abms import guardrails, metrics  # noqa: E402
from abms.carbon import intensity_for_hour  # noqa: E402
from abms.comfort import pmv_for_zone  # noqa: E402
from abms.controllers.mcp_bridge import MCPBridgeController  # noqa: E402
from abms.controllers.rulebased import RuleBasedController  # noqa: E402
from abms.datastore import SharedState  # noqa: E402
from abms.decision_handshake import APPLIED_RESULT_TIMEOUT_S, DEFAULT_TIMEOUT_S, DecisionHandshake  # noqa: E402
from abms.simulation import SimulationRunner  # noqa: E402
from abms.telemetry import ZONE_NAMES  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_IDF = REPO_ROOT / "models" / "building.idf"
DEFAULT_EPW = REPO_ROOT / "models" / "weather" / "USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw"


def build_server(
    datastore: SharedState,
    handshake: DecisionHandshake,
    decision_interval_minutes: int,
    peak_demand_kw_threshold: float | None = None,
) -> FastMCP:
    """Build the FastMCP app. Kept out of main() so tests can construct a
    server without starting EnergyPlus."""
    mcp = FastMCP(name="abms-controller")

    @mcp.tool()
    def get_building_state() -> dict:
        """Current snapshot of the building. Call this first each cycle.

        Per zone: air temperature (C), occupant count, and PMV comfort
        index (target |PMV| <= 0.5). Plus outdoor temperature (C), the
        current heating and cooling setpoints (C), HVAC power as interval
        kWh and as average kW (current_demand_kw, to compare against the
        peak-demand threshold), the simulation datetime, and whether a
        decision is awaited right now (awaiting_decision).
        """
        latest = datastore.latest()
        if latest is None:
            return {"error": "No simulation state recorded yet."}
        month = int(latest["timestamp"][5:7])
        zones = {
            z: {
                "temp_c": latest[f"zone_temp_c_{z}"],
                "occupant_count": latest[f"zone_occupant_count_{z}"],
                "pmv": pmv_for_zone(latest[f"zone_temp_c_{z}"], month),
            }
            for z in ZONE_NAMES
        }
        total_occupants = sum(z["occupant_count"] for z in zones.values())
        history_rows = datastore.history()
        interval_min = metrics.interval_minutes(history_rows) if history_rows else metrics.DEFAULT_INTERVAL_MINUTES
        return {
            "sim_datetime": latest["timestamp"],
            "outdoor_temp_c": latest["outdoor_temp_c"],
            "zones": zones,
            "occupied": total_occupants > 0,
            "current_setpoints": {
                "heating_c": latest["heating_setpoint_c"],
                "cooling_c": latest["cooling_setpoint_c"],
            },
            "current_power": {
                "hvac_electricity_interval_kwh": latest["hvac_electricity_interval_kwh"],
                "hvac_gas_interval_kwh": latest["hvac_gas_interval_kwh"],
                "current_demand_kw": metrics.interval_kwh_to_kw(
                    latest["hvac_electricity_interval_kwh"], interval_min
                ),
            },
            "awaiting_decision": handshake.awaiting_decision,
        }

    @mcp.tool()
    def get_recent_history(hours: int = 24) -> dict:
        """Hourly history for the last `hours` sim-hours.

        Per hour: mean zone temperature (C), mean outdoor temperature (C),
        HVAC electricity and gas (kWh), and whether the building was
        occupied. Use it to spot trends, such as a temperature drifting
        toward the comfort floor, before deciding.
        """
        rows = datastore.history()
        buckets = defaultdict(list)
        for r in rows:
            buckets[r["timestamp"][:13]].append(r)  # "YYYY-MM-DDTHH"
        hourly = []
        for hour_key in sorted(buckets)[-max(hours, 1):]:
            bucket = buckets[hour_key]
            n = len(bucket)
            total_occupants = sum(sum(r[f"zone_occupant_count_{z}"] for z in ZONE_NAMES) for r in bucket)
            mean_zone_temp = sum(
                sum(r[f"zone_temp_c_{z}"] for z in ZONE_NAMES) / len(ZONE_NAMES) for r in bucket
            ) / n
            hourly.append(
                {
                    "hour": hour_key + ":00",
                    "mean_zone_temp_c": mean_zone_temp,
                    "mean_outdoor_temp_c": sum(r["outdoor_temp_c"] for r in bucket) / n,
                    "hvac_electricity_kwh": sum(r["hvac_electricity_interval_kwh"] for r in bucket),
                    "hvac_gas_kwh": sum(r["hvac_gas_interval_kwh"] for r in bucket),
                    "occupied": total_occupants > 0,
                }
            )
        return {"hourly": hourly}

    @mcp.tool()
    def get_goals_and_constraints() -> dict:
        """Objectives and hard limits.

        Comfort is a constraint and must hold during occupied hours.
        Energy, carbon and peak demand are objectives. Returns the
        occupied comfort band and PMV target, the guardrail bounds that
        will clamp any request you make, the peak-demand threshold, the
        decision cadence, and a carbon intensity forecast for the current
        hour and the next six, so load can be shifted to cleaner hours.
        """
        latest = datastore.latest()
        current_hour = int(latest["timestamp"][11:13]) if latest else 0
        forecast = [
            {"hour_offset": i, "intensity_kg_per_kwh": intensity_for_hour(current_hour + i)} for i in range(7)
        ]
        return {
            "goals": {
                "comfort": "constraint: must hold during occupied hours",
                "energy": "objective: minimize HVAC electricity + gas",
                "carbon": "objective: minimize kg CO2; prefer shifting load to low-intensity hours",
                "peak_demand": {
                    "threshold_kw": peak_demand_kw_threshold,
                    "guidance": "keep instantaneous HVAC demand below this; pre-conditioning earlier "
                    "is preferable to peak-hour catch-up",
                },
            },
            "occupied_comfort_band_c": {
                "heat_floor": guardrails.OCCUPIED_HEAT_FLOOR_C,
                "cool_ceiling": guardrails.OCCUPIED_COOL_CEILING_C,
            },
            "pmv_target": {
                "abs_max": metrics.PMV_COMFORT_THRESHOLD,
                "guidance": "keep each occupied zone's |PMV| at or below this (ASHRAE 55)",
            },
            "guardrail_bounds_c": {
                "heating_min": guardrails.HEATING_MIN_C,
                "heating_max": guardrails.HEATING_MAX_C,
                "cooling_min": guardrails.COOLING_MIN_C,
                "cooling_max": guardrails.COOLING_MAX_C,
                "min_deadband": guardrails.MIN_DEADBAND_C,
                "max_step_per_decision_c": guardrails.MAX_STEP_C,
            },
            "decision_interval_minutes": decision_interval_minutes,
            "carbon_intensity_forecast": forecast,
        }

    @mcp.tool()
    def set_zone_setpoints(heating_c: float, cooling_c: float, reasoning: str = "") -> dict:
        """Submit heating and cooling setpoints (deg C, all zones).

        Only valid while get_building_state reports awaiting_decision:
        true; otherwise the call is rejected. The guardrail layer may
        clamp the request, so the response reports what you asked for,
        what was applied, and the reason for any clamp. Adjust your next
        decision accordingly.

        Always pass `reasoning`: one or two sentences, stored verbatim in
        the decision log.
        """
        pending = handshake.submit_decision(heating_c, cooling_c, reasoning=reasoning or None)
        if pending is None:
            return {
                "accepted": False,
                "reason": "No decision is pending. Call get_building_state and check "
                "awaiting_decision.",
            }
        try:
            entry = pending.result_queue.get(timeout=APPLIED_RESULT_TIMEOUT_S)
        except _queue.Empty:
            return {
                "accepted": True,
                "applied": None,
                "reason": f"Submitted, but no confirmation within {APPLIED_RESULT_TIMEOUT_S}s.",
            }
        return {
            "accepted": True,
            "requested": entry["requested"],
            "applied": entry["applied"],
            "guardrail_notes": entry["guardrail_notes"],
        }

    @mcp.tool()
    def get_performance_so_far() -> dict:
        """Cumulative HVAC energy so far, comfort compliance and carbon
        over the trailing 24h, and the number of decisions made. Use it to
        check that recent decisions are trending the right way."""
        latest = datastore.latest()
        if latest is None:
            return {"error": "No simulation state recorded yet."}
        window_rows = datastore.history()
        return {
            "cumulative_hvac_electricity_kwh": latest["hvac_electricity_cumulative_kwh"],
            "cumulative_hvac_gas_kwh": latest["hvac_gas_cumulative_kwh"],
            "trailing_24h_window": {
                "comfort_compliance_pct": metrics.comfort_compliance_pct(window_rows),
                "carbon_kg": metrics.total_carbon_kg(window_rows),
            },
            "decisions_made": datastore.decisions_count(),
        }

    return mcp


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--idf", default=str(DEFAULT_IDF))
    parser.add_argument("--epw", default=str(DEFAULT_EPW))
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "runs" / "mcp_session"))
    parser.add_argument("--run-id", default="mcp_session")
    parser.add_argument("--decision-interval-minutes", type=int, default=15)
    parser.add_argument("--timeout-s", type=float, default=DEFAULT_TIMEOUT_S)
    args = parser.parse_args(argv)

    datastore = SharedState()
    handshake = DecisionHandshake(timeout_s=args.timeout_s)
    controller = MCPBridgeController(handshake, fallback_controller=RuleBasedController())

    def on_decision(entry: dict) -> None:
        datastore.record_decision(entry)
        handshake.publish_result(entry)

    runner = SimulationRunner(
        idf_path=args.idf,
        epw_path=args.epw,
        output_dir=args.output_dir,
        run_id=args.run_id,
        mode="mcp",
        controller=controller,
        decision_interval_minutes=args.decision_interval_minutes,
        on_state=datastore.update,
        on_decision=on_decision,
        mute_console=True,
    )
    runner.start()

    peak_demand_kw_threshold = config.load().get("peak_demand_kw_threshold")
    mcp = build_server(datastore, handshake, args.decision_interval_minutes, peak_demand_kw_threshold)
    try:
        mcp.run(transport="stdio")
    finally:
        runner.join(timeout=5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
