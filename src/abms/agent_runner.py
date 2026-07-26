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

# GC-4b native tool-calling mode. Bounded agentic loop per decision -- a cap,
# not a target, so a model that never converges on set_zone_setpoints can't
# hang a decision forever; the caller falls through to structured mode
# instead (three-layer fallback: native -> structured -> rule-based).
NATIVE_MAX_ROUNDS = 6
# Native decisions cost 2-4 completions at 17-26s each (40-100s) -- plausibly
# over the 60s handshake timeout, so native sessions launch mcp_server with a
# larger timeout (docs/GAP_CLOSURE_PLAN.md §2 GC-4b wall-clock note).
NATIVE_TIMEOUT_S = 180.0


class NativeToolCallError(RuntimeError):
    """Raised when the native tool-calling loop fails for any reason -- no
    tool call in a round, an unknown tool name, missing/invalid arguments to
    set_zone_setpoints, the round cap, or any other exception. Callers catch
    this and fall through to the existing structured-mode path for that same
    decision (GC-4b's first safety net; structured mode's own
    OllamaUnavailableError/DecisionParseError handling is the second)."""


def _mcp_tool_to_ollama(tool) -> dict:
    """Translates one MCP `Tool` (name/description/inputSchema) into the
    Ollama chat API's `tools=` function-calling format."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.inputSchema or {"type": "object", "properties": {}},
        },
    }


def build_native_system_prompt(structured_prompt: str) -> str:
    """Native mode reuses the goals/constraints/examples content of the
    structured-mode system prompt (`prompts/controller_system.md`) verbatim,
    dropping only the JSON-output section (irrelevant here) in favor of
    tool-calling instructions -- additive: the prompt file itself is
    untouched, so structured mode is unaffected."""
    goals_section = structured_prompt.split("## Required output format")[0]
    return (
        goals_section
        + "## How you act in this mode\n\n"
        "You have tools available to read building state, goals/constraints, "
        "and recent history, and to submit your decision. Call read-tools as "
        "needed, then call `set_zone_setpoints` exactly once to submit your "
        "heating_c/cooling_c decision with a short `reasoning` string. You "
        "are not finished until you have called `set_zone_setpoints`.\n"
    )


async def run_native_decision(
    session: ClientSession,
    tools_spec: list,
    ollama_client,
    model: str,
    temperature: float,
    system_prompt: str,
    max_rounds: int = NATIVE_MAX_ROUNDS,
) -> dict:
    """One decision cycle in native tool-calling mode (GC-4b §2): the model
    drives its own MCP tool calls (translated to Ollama's `tools=` format at
    session start) instead of the runner prefetching state/goals/history.
    Returns `{"heating_c", "cooling_c", "reasoning", "write_result"}` once
    `set_zone_setpoints` has been called and accepted. Raises
    `NativeToolCallError` on any failure so the caller can fall through to
    structured mode for this same decision."""
    tool_names = {t["function"]["name"] for t in tools_spec}
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                "Decide the next heating and cooling setpoints for this "
                "building. Use the tools to gather state before deciding, "
                "then call set_zone_setpoints exactly once to finish."
            ),
        },
    ]

    for _ in range(max_rounds):
        try:
            response = ollama_client.chat(
                model=model,
                messages=messages,
                tools=tools_spec,
                options={"temperature": temperature},
            )
        except Exception as e:
            raise NativeToolCallError(f"native chat call failed: {e}") from e

        message = response["message"]
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            raise NativeToolCallError("model returned no tool call")
        messages.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": tool_calls})

        for call in tool_calls:
            name = call["function"]["name"]
            arguments = call["function"]["arguments"] or {}
            if name not in tool_names:
                raise NativeToolCallError(f"model called unknown tool {name!r}")
            if name == "set_zone_setpoints" and not (
                isinstance(arguments.get("heating_c"), (int, float)) and isinstance(arguments.get("cooling_c"), (int, float))
            ):
                raise NativeToolCallError(f"set_zone_setpoints called with invalid arguments {arguments!r}")
            try:
                result = await _call(session, name, arguments)
            except Exception as e:
                raise NativeToolCallError(f"tool call {name!r} failed: {e}") from e
            messages.append({"role": "tool", "content": json.dumps(result)})

            if name == "set_zone_setpoints":
                if not result.get("accepted"):
                    raise NativeToolCallError(f"set_zone_setpoints rejected: {result.get('reason')}")
                applied = result.get("applied") or {}
                return {
                    "heating_c": applied.get("heating_c"),
                    "cooling_c": applied.get("cooling_c"),
                    "reasoning": arguments.get("reasoning", ""),
                    "write_result": result,
                }

    raise NativeToolCallError(f"round cap ({max_rounds}) reached without set_zone_setpoints")


def expected_decision_count(period_days: float, decision_interval_minutes: int) -> int:
    return math.ceil(period_days * 24 * 60 / decision_interval_minutes)


def _log(line: str) -> None:
    print(line, flush=True)


async def _call(session: ClientSession, tool: str, arguments: dict | None = None) -> dict:
    result = await session.call_tool(tool, arguments or {})
    if result.structuredContent is not None:
        return result.structuredContent
    try:
        return json.loads(result.content[0].text)
    except Exception as e:
        raise RuntimeError(f"could not parse {tool!r} result: {e} -- content={result.content!r}") from e


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
    mode: str = "structured",
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
    native_decisions = 0
    native_fallback_decisions = 0
    last_sim_datetime = None
    last_progress_at = time.monotonic()
    previous_feedback = None

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            _log(f"[agent_runner] session initialized -- run_id={run_id} target~{max_decisions} decisions mode={mode}")

            native_tools_spec = None
            native_system_prompt = None
            if mode == "native":
                tools_result = await session.list_tools()
                native_tools_spec = [_mcp_tool_to_ollama(t) for t in tools_result.tools]
                native_system_prompt = build_native_system_prompt(llm_agent.system_prompt)

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

                source = None
                write_result = None
                native_attempted = False
                if mode == "native":
                    native_attempted = True
                    try:
                        native = await run_native_decision(
                            session,
                            native_tools_spec,
                            llm_agent.client,
                            llm_agent.model,
                            llm_agent.temperature,
                            native_system_prompt,
                        )
                        source = "llm-native"
                        heating_c, cooling_c, reasoning = native["heating_c"], native["cooling_c"], native["reasoning"]
                        write_result = native["write_result"]
                        native_decisions += 1
                    except NativeToolCallError as e:
                        native_fallback_decisions += 1
                        _log(
                            f"[agent_runner] ALERT: native tool-calling failed at "
                            f"{state.get('sim_datetime')} -- {e} -- falling back to structured mode "
                            "for this decision"
                        )

                if source is None:
                    fallback_reason = None
                    try:
                        decision = llm_agent.propose(state, goals, history, previous_feedback=previous_feedback)
                        heating_c, cooling_c, reasoning = decision.heating_c, decision.cooling_c, decision.reasoning
                        source = "structured-after-native-failure" if native_attempted else "llm"
                    except OllamaUnavailableError as e:
                        source, fallback_reason = "fallback-ollama-unavailable", str(e)
                    except DecisionParseError as e:
                        source, fallback_reason = "fallback-malformed-output", str(e)

                    if source in ("fallback-ollama-unavailable", "fallback-malformed-output"):
                        _log(f"[agent_runner] ALERT: {source} at {state.get('sim_datetime')} -- {fallback_reason}")
                        heating_c, cooling_c = fallback_controller.decide(state)
                        reasoning = f"[{source}] {fallback_reason}"
                        fallback_decisions += 1
                    else:
                        llm_decisions += 1

                if write_result is None:
                    write_result = await _call(
                        session,
                        "set_zone_setpoints",
                        {"heating_c": heating_c, "cooling_c": cooling_c, "reasoning": reasoning},
                    )
                decisions_made += 1
                last_progress_at = time.monotonic()
                previous_feedback = write_result

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
        f"({llm_decisions} llm, {fallback_decisions} runner-side fallback, "
        f"{native_decisions} llm-native, {native_fallback_decisions} native->structured fallback)"
    )
    return {
        "run_id": run_id,
        "mode": mode,
        "decisions_made": decisions_made,
        "llm_decisions": llm_decisions,
        "fallback_decisions": fallback_decisions,
        "native_decisions": native_decisions,
        "native_fallback_decisions": native_fallback_decisions,
    }


def build_llm_agent(overrides: dict | None = None) -> tuple[LLMAgent, int, str]:
    """Loads `config/default.yaml`'s `llm_agent` section (env-overridable
    per §1.2), returns a constructed `LLMAgent` plus `history_hours`
    (not an `LLMAgent` constructor arg -- it's how much `get_recent_history`
    the runner asks for) plus `mode` (GC-4b, "structured" | "native", also
    not an `LLMAgent` constructor arg -- it's how `run_agent_session`
    decides whether to attempt native tool-calling before structured)."""
    cfg = config.llm_agent_config()
    cfg.update(overrides or {})
    history_hours = cfg.pop("history_hours")
    mode = cfg.pop("mode", "structured")
    return LLMAgent(**cfg), history_hours, mode


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--idf", default=str(DEFAULT_IDF))
    parser.add_argument("--epw", default=str(DEFAULT_EPW))
    parser.add_argument("--run-id", default="ai")
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "runs" / "ai_session" / "ai"))
    parser.add_argument("--decision-interval-minutes", type=int, default=None)
    parser.add_argument("--timeout-s", type=float, default=None)
    parser.add_argument("--period-days", type=float, required=True, help="Sim days covered by --idf's RunPeriod.")
    parser.add_argument(
        "--mode",
        choices=["structured", "native"],
        default=None,
        help="Overrides config/default.yaml's llm_agent.mode (GC-4b). Structured is production; "
        "native is a time-boxed showcase mode.",
    )
    args = parser.parse_args(argv)

    cfg = config.load()
    decision_interval = args.decision_interval_minutes or cfg["decision_interval_minutes"]["llm"]
    llm_agent, history_hours, config_mode = build_llm_agent()
    mode = args.mode or config_mode
    # Native decisions run 2-4 completions per decision (40-100s) -- raise
    # the handshake timeout so a native decision can't outlive it (GC-4b
    # wall-clock note); structured mode keeps the existing 60s default.
    timeout_s = args.timeout_s if args.timeout_s is not None else (NATIVE_TIMEOUT_S if mode == "native" else 60.0)
    max_decisions = expected_decision_count(args.period_days, decision_interval) + 2  # small buffer

    report = asyncio.run(
        run_agent_session(
            idf_path=args.idf,
            epw_path=args.epw,
            output_dir=args.output_dir,
            run_id=args.run_id,
            decision_interval_minutes=decision_interval,
            timeout_s=timeout_s,
            max_decisions=max_decisions,
            llm_agent=llm_agent,
            history_hours=history_hours,
            mode=mode,
        )
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
