"""Exercises the decision handshake against a real mcp_server subprocess.

Two paths:

1. Happy: get_building_state, set_zone_setpoints, then check the next
   get_building_state reflects the applied setpoints.
2. Timeout: never answer a pending decision, and check the fallback
   controller's decision is applied and the run continues.

Prints every call and response so the output can be kept as evidence.
"""

import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = REPO_ROOT / "runs" / "phase3_mcp_test"
POLL_INTERVAL_S = 0.5
POLL_TIMEOUT_S = 90.0


def _log(line: str) -> None:
    print(line)
    sys.stdout.flush()


def _server_params(run_id: str, timeout_s: float, decision_interval_minutes: int = 15) -> StdioServerParameters:
    output_dir = RUNS_DIR / run_id
    return StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "abms.mcp_server",
            "--run-id",
            run_id,
            "--output-dir",
            str(output_dir),
            "--decision-interval-minutes",
            str(decision_interval_minutes),
            "--timeout-s",
            str(timeout_s),
        ],
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
    )


async def _call(session: ClientSession, tool: str, arguments: dict | None = None) -> dict:
    _log(f">>> call_tool({tool!r}, {arguments!r})")
    result = await session.call_tool(tool, arguments or {})
    payload = json.loads(result.content[0].text)
    _log(f"<<< {json.dumps(payload, indent=2)}")
    return payload


async def _poll_until_awaiting_decision(session: ClientSession) -> dict:
    deadline = time.monotonic() + POLL_TIMEOUT_S
    while time.monotonic() < deadline:
        state = await _call(session, "get_building_state")
        if state.get("awaiting_decision"):
            return state
        await asyncio.sleep(POLL_INTERVAL_S)
    raise TimeoutError("Simulation never reached a decision point within the poll timeout.")


async def _poll_until_sim_advanced(session: ClientSession, since_sim_datetime: str) -> dict:
    """Waits for sim time to move past `since_sim_datetime` -- i.e. the
    decision that was pending at that timestamp has been resolved (applied
    or fallen back) and the simulation proceeded. Note: this model's zone
    timestep equals its decision interval, so a *new* decision point is
    typically already pending again by the time this returns -- that's
    expected, not a bug, and is why we check sim-time movement rather than
    `awaiting_decision` flipping to False."""
    deadline = time.monotonic() + POLL_TIMEOUT_S
    while time.monotonic() < deadline:
        state = await _call(session, "get_building_state")
        if state["sim_datetime"] != since_sim_datetime:
            return state
        await asyncio.sleep(POLL_INTERVAL_S)
    raise TimeoutError("Simulation never advanced past the pending decision within the poll timeout.")


async def run_happy_path() -> None:
    _log("\n" + "=" * 72)
    _log("HAPPY PATH: state read -> setpoint write -> sim advances -> reflected")
    _log("=" * 72)

    params = _server_params("happy_path", timeout_s=60.0)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            _log("session initialized")

            state = await _poll_until_awaiting_decision(session)
            before_sim_datetime = state["sim_datetime"]
            occupied = state["occupied"]

            # Mirror the rule-based controller's setpoints for the current
            # occupancy so the request passes guardrails unclamped -- a clean
            # demonstration of the accepted-as-requested path.
            if occupied:
                heating_c, cooling_c = 21.0, 24.0
            else:
                heating_c, cooling_c = 18.3, 28.0

            goals = await _call(session, "get_goals_and_constraints")
            assert "occupied_comfort_band_c" in goals

            write_result = await _call(session, "set_zone_setpoints", {"heating_c": heating_c, "cooling_c": cooling_c})
            assert write_result["accepted"] is True, write_result
            assert write_result["applied"] is not None, "no applied-result confirmation"
            applied = write_result["applied"]
            _log(f"applied setpoints: heating={applied['heating_c']} cooling={applied['cooling_c']}")

            after = await _poll_until_sim_advanced(session, before_sim_datetime)
            assert after["sim_datetime"] != before_sim_datetime, "sim time did not advance"
            assert after["current_setpoints"]["heating_c"] == applied["heating_c"]
            assert after["current_setpoints"]["cooling_c"] == applied["cooling_c"]

            perf = await _call(session, "get_performance_so_far")
            assert perf["decisions_made"] >= 1

            history = await _call(session, "get_recent_history", {"hours": 24})
            assert len(history["hourly"]) >= 1, "expected at least one hourly bucket by now"
            assert "mean_zone_temp_c" in history["hourly"][-1]

            _log(
                f"\nPASS: sim advanced from {before_sim_datetime} to {after['sim_datetime']}; "
                f"next state's setpoints ({after['current_setpoints']}) match the applied write."
            )


async def run_timeout_path() -> None:
    _log("\n" + "=" * 72)
    _log("TIMEOUT PATH: client never responds -- fallback must take over")
    _log("=" * 72)

    timeout_s = 3.0
    params = _server_params("timeout_path", timeout_s=timeout_s)
    stderr_path = RUNS_DIR / "timeout_path" / "server_stderr.log"
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    with open(stderr_path, "w") as errlog:
        async with stdio_client(params, errlog=errlog) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                _log("session initialized")

                state = await _poll_until_awaiting_decision(session)
                before_sim_datetime = state["sim_datetime"]
                occupied = state["occupied"]
                _log(
                    f"decision pending at {before_sim_datetime} (occupied={occupied}) -- "
                    f"deliberately NOT calling set_zone_setpoints; waiting for the "
                    f"{timeout_s}s handshake timeout to fire..."
                )

                # Deliberate silence: no set_zone_setpoints call. Just wait
                # past the server's --timeout-s for the fallback to fire.
                await asyncio.sleep(timeout_s + 2.0)

                after = await _poll_until_sim_advanced(session, before_sim_datetime)
                _log(f"state after timeout: {json.dumps(after, indent=2)}")

                expected_heat, expected_cool = (21.0, 24.0) if occupied else (18.3, 28.0)
                assert after["current_setpoints"]["heating_c"] == expected_heat, after["current_setpoints"]
                assert after["current_setpoints"]["cooling_c"] == expected_cool, after["current_setpoints"]

    server_stderr = stderr_path.read_text()
    _log("\n--- server stderr (proves the timeout fired and was logged loudly) ---")
    _log(server_stderr)
    assert "TIMEOUT" in server_stderr, "expected a loud TIMEOUT log line in server stderr"

    _log(
        f"\nPASS: after the {timeout_s}s timeout, setpoints ({expected_heat}, {expected_cool}) "
        f"matching the rule-based fallback were applied, sim time advanced, and the timeout "
        f"was logged loudly to stderr."
    )


async def main() -> None:
    if RUNS_DIR.exists():
        shutil.rmtree(RUNS_DIR)
    await run_happy_path()
    await run_timeout_path()
    _log("\nALL PHASE 3 VALIDATION CHECKS PASSED.")


if __name__ == "__main__":
    asyncio.run(main())
