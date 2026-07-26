"""The AI agent runner (§4.1, §6): the MCP *client* side of the closed
loop. Spawns `abms.mcp_server` as a stdio subprocess (the same tested
Phase 3 server -- sim and MCP server share one process; this runner is a
separate process talking to it over stdio, exactly like
`scripts/test_mcp_handshake.py`), and at every decision point calls the
read-tools, asks the LLM agent (`controllers/llm_agent.py`) for a decision,
and submits it via the write-tool.

Robustness (§4.4), built on top of the Phase 3 handshake rather than
duplicating it: a malformed-JSON-after-retry or an unreachable Ollama both
result in this runner computing the same rule-based decision the sim
thread would fall back to on timeout, and submitting it itself (with a
reasoning string explaining why) -- so a decision is never late waiting out
the full handshake timeout just because Ollama is down. The handshake's own
60s timeout (§3.3) remains the second line of defense in case this process
itself dies or hangs.
"""

import argparse
import asyncio
import json
import math
import os
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from abms import config
from abms.controllers.llm_agent import LLMAgent, OllamaUnavailableError
from abms.controllers.rulebased import RuleBasedController
from abms.decision_parsing import DecisionParseError

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_IDF = REPO_ROOT / "models" / "building.idf"
DEFAULT_EPW = REPO_ROOT / "models" / "weather" / "USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw"

POLL_INTERVAL_S = 0.5
# How long to wait, with no sim-time movement at all, before concluding the
# simulation has ended (or hung) and it's time to disconnect -- generous
# relative to the handshake timeout since a stalled poll is not itself a
# fault, just the signal this runner uses to know when to stop.
STALL_TIMEOUT_S = 120.0


def expected_decision_count(period_days: float, decision_interval_minutes: int) -> int:
    return math.ceil(period_days * 24 * 60 / decision_interval_minutes)


def _log(line: str) -> None:
    print(line, flush=True)


async def _call(session: ClientSession, tool: str, arguments: dict | None = None) -> dict:
    result = await session.call_tool(tool, arguments or {})
    return json.loads(result.content[0].text)


async def run_agent_session(
    *,
    idf_path=DEFAULT_IDF,
    epw_path=DEFAULT_EPW,
    output_dir,
    run_id: str,
    decision_interval_minutes: int,
    timeout_s: float,
    max_decisions: int,
    llm_agent: LLMAgent,
    history_hours: int,
    fallback_controller=None,
) -> dict:
    """Drives one full AI-controlled simulation to completion. Returns a
    small run report (decisions made, how many used the LLM vs a runner-
    side fallback, and why). Stops once `max_decisions` decisions have been
    made (the run period, translated to an expected decision count by the
    caller -- §4.4's config-driven demo period) or the sim goes quiet for
    `STALL_TIMEOUT_S` (end of run, or a hang either MCP-side handshake
    timeout should already have prevented)."""
    fallback_controller = fallback_controller or RuleBasedController()

    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "abms.mcp_server",
            "--idf",
            str(idf_path),
            "--epw",
            str(epw_path),
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

    decisions_made = 0
    llm_decisions = 0
    fallback_decisions = 0
    last_sim_datetime = None
    last_progress_at = time.monotonic()

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            _log(f"[agent_runner] session initialized -- run_id={run_id} target~{max_decisions} decisions")

            while decisions_made < max_decisions:
                state = await _call(session, "get_building_state")
                if state.get("sim_datetime") != last_sim_datetime:
                    last_sim_datetime = state.get("sim_datetime")
                    last_progress_at = time.monotonic()
                elif time.monotonic() - last_progress_at > STALL_TIMEOUT_S:
                    _log(
                        f"[agent_runner] no sim-time movement for {STALL_TIMEOUT_S}s at "
                        f"{last_sim_datetime} -- assuming the run has ended (or stalled) and disconnecting."
                    )
                    break

                if not state.get("awaiting_decision"):
                    await asyncio.sleep(POLL_INTERVAL_S)
                    continue

                goals = await _call(session, "get_goals_and_constraints")
                history = await _call(session, "get_recent_history", {"hours": history_hours})

                source = "llm"
                fallback_reason = None
                try:
                    decision = llm_agent.propose(state, goals, history)
                    heating_c, cooling_c, reasoning = decision.heating_c, decision.cooling_c, decision.reasoning
                except OllamaUnavailableError as e:
                    source, fallback_reason = "fallback-ollama-unavailable", str(e)
                except DecisionParseError as e:
                    source, fallback_reason = "fallback-malformed-output", str(e)

                if source != "llm":
                    _log(f"[agent_runner] ALERT: {source} at {state.get('sim_datetime')} -- {fallback_reason}")
                    heating_c, cooling_c = fallback_controller.decide(state)
                    reasoning = f"[{source}] {fallback_reason}"
                    fallback_decisions += 1
                else:
                    llm_decisions += 1

                write_result = await _call(
                    session,
                    "set_zone_setpoints",
                    {"heating_c": heating_c, "cooling_c": cooling_c, "reasoning": reasoning},
                )
                decisions_made += 1
                last_progress_at = time.monotonic()

                applied = write_result.get("applied") or {}
                _log(
                    f"[{state.get('sim_datetime')}] occupied={state.get('occupied')} source={source}\n"
                    f"  reasoning: {reasoning}\n"
                    f"  requested: heating={heating_c:.1f} cooling={cooling_c:.1f}"
                    f"  applied: heating={applied.get('heating_c')} cooling={applied.get('cooling_c')}"
                    f"  guardrail_notes={write_result.get('guardrail_notes')}"
                )

    _log(
        f"[agent_runner] done -- {decisions_made} decisions "
        f"({llm_decisions} llm, {fallback_decisions} runner-side fallback)"
    )
    return {
        "run_id": run_id,
        "decisions_made": decisions_made,
        "llm_decisions": llm_decisions,
        "fallback_decisions": fallback_decisions,
    }


def build_llm_agent(overrides: dict | None = None) -> tuple[LLMAgent, int]:
    """Loads `config/default.yaml`'s `llm_agent` section (env-overridable
    per §1.2), returns a constructed `LLMAgent` plus `history_hours`
    (not an `LLMAgent` constructor arg -- it's how much `get_recent_history`
    the runner asks for)."""
    cfg = config.llm_agent_config()
    cfg.update(overrides or {})
    history_hours = cfg.pop("history_hours")
    return LLMAgent(**cfg), history_hours


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--idf", default=str(DEFAULT_IDF))
    parser.add_argument("--epw", default=str(DEFAULT_EPW))
    parser.add_argument("--run-id", default="ai")
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "runs" / "ai_session" / "ai"))
    parser.add_argument("--decision-interval-minutes", type=int, default=None)
    parser.add_argument("--timeout-s", type=float, default=60.0)
    parser.add_argument("--period-days", type=float, required=True, help="Sim days covered by --idf's RunPeriod.")
    args = parser.parse_args(argv)

    cfg = config.load()
    decision_interval = args.decision_interval_minutes or cfg["decision_interval_minutes"]["llm"]
    llm_agent, history_hours = build_llm_agent()
    max_decisions = expected_decision_count(args.period_days, decision_interval) + 2  # small buffer

    report = asyncio.run(
        run_agent_session(
            idf_path=args.idf,
            epw_path=args.epw,
            output_dir=args.output_dir,
            run_id=args.run_id,
            decision_interval_minutes=decision_interval,
            timeout_s=args.timeout_s,
            max_decisions=max_decisions,
            llm_agent=llm_agent,
            history_hours=history_hours,
        )
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
