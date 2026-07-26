#!/usr/bin/env python3
"""
ABMS live demo - MCP TOOL-CALL TRACER.

Shows the part of the loop the main demo cannot: the actual MCP traffic
between the agent and EnergyPlus. Everything printed here is a real call to a
real `abms.mcp_server` subprocess driving a real EnergyPlus simulation.

It performs, on camera, exactly what `agent_runner` does every cycle:

    1. list_tools()               -- the tool surface the LLM is given
    2. get_building_state()       -- live physics state out of EnergyPlus
    3. get_goals_and_constraints()
    4. get_recent_history()
    5. (--show-prompt) assembles the real prompt from those 3 responses
    6. (--provoke-clamp) set_zone_setpoints() with an out-of-bounds value,
       so the guardrail layer clamps it live instead of via a grepped log

HONEST FRAMING FOR NARRATION
    This starts its OWN mcp_server + EnergyPlus instance. It is not attached
    to the run in your other pane -- an MCP stdio server has exactly one
    client, by design. Say so: "same server, same five tools, same code path,
    a second instance so we can watch the wire."

    Output goes to runs/tool_trace/, which is gitignored - it never lands in
    a committed run directory.

USAGE
    python scripts/tool_call_trace.py                   # the 4 read tools
    python scripts/tool_call_trace.py --show-prompt     # + the assembled LLM prompt
    python scripts/tool_call_trace.py --provoke-clamp   # + a live guardrail clamp
    python scripts/tool_call_trace.py --slow 1.5        # pause between calls, for camera
"""

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "runs" / "tool_trace"

sys.path.insert(0, str(REPO / "src"))

from mcp import ClientSession, StdioServerParameters      # noqa: E402
from mcp.client.stdio import stdio_client                 # noqa: E402

ESC = ""
RESET = BOLD = DIM = ""
BLUE = ORANGE = AQUA = ""
GREY = WHITE = RED = ""
YELLOW = INVERT = ""

POLL_INTERVAL_S = 0.5
POLL_TIMEOUT_S = 180.0


def rule(title, color=BLUE):
    w = min(shutil.get_terminal_size((100, 40)).columns, 100)
    print(f"\n{color}{'=' * w}{RESET}")
    print(f"{BOLD}{color}  {title}{RESET}")
    print(f"{color}{'=' * w}{RESET}")


def jdump(payload, limit=None):
    text = json.dumps(payload, indent=2)
    lines = text.splitlines()
    if limit and len(lines) > limit:
        lines = lines[:limit] + [f"{GREY}  ... ({len(text.splitlines()) - limit} more lines){RESET}"]
    for ln in lines:
        print(f"  {WHITE}{ln}{RESET}")


async def call(session, tool, arguments=None, slow=0.0, limit=None):
    print(f"\n{AQUA}> call_tool{RESET}({BOLD}{tool}{RESET}, {arguments or {}})")
    t0 = time.monotonic()
    result = await session.call_tool(tool, arguments or {})
    dt = (time.monotonic() - t0) * 1000
    payload = json.loads(result.content[0].text)
    print(f"{GREY}< response in {dt:.0f} ms{RESET}")
    jdump(payload, limit)
    if slow:
        await asyncio.sleep(slow)
    return payload


async def main_async(args):
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m", "abms.mcp_server",
            "--idf", str(REPO / "models" / "building.idf"),
            "--epw", str(REPO / "models" / "weather" /
                         "USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw"),
            "--run-id", "tool_trace",
            "--output-dir", str(OUT_DIR),
            "--decision-interval-minutes", "60",
            "--timeout-s", "120",
        ],
        env={**os.environ, "PYTHONPATH": str(REPO / "src")},
    )

    print(f"{GREY}starting a real abms.mcp_server + EnergyPlus subprocess...{RESET}")
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # ---------- 1. the tool surface ----------
            rule("1. list_tools()  - the tool surface the LLM is handed", BLUE)
            tools = (await session.list_tools()).tools
            for t in tools:
                first = (t.description or "").strip().split(". ")[0]
                props = list((t.inputSchema or {}).get("properties", {}).keys())
                sig = ", ".join(props) if props else ""
                print(f"\n  {BOLD}{AQUA}{t.name}{RESET}({GREY}{sig}{RESET})")
                for ln in _wrap(first, 88):
                    print(f"      {GREY}{ln}{RESET}")
            print(f"\n  {BOLD}{len(tools)} tools{RESET}{GREY} - four read, one write.{RESET}")
            if args.slow:
                await asyncio.sleep(args.slow * 2)

            # ---------- 2. wait for a decision point ----------
            rule("2. polling get_building_state() until EnergyPlus wants a decision", ORANGE)
            deadline = time.monotonic() + POLL_TIMEOUT_S
            state, polls = None, 0
            while time.monotonic() < deadline:
                result = await session.call_tool("get_building_state", {})
                state = json.loads(result.content[0].text)
                polls += 1
                if state.get("awaiting_decision"):
                    break
                sys.stdout.write(f"\r  {GREY}poll {polls}: sim_datetime="
                                 f"{state.get('sim_datetime')} awaiting_decision=False{RESET}   ")
                sys.stdout.flush()
                await asyncio.sleep(POLL_INTERVAL_S)
            print(f"\r  {AQUA}awaiting_decision=True{RESET} after {polls} polls "
                  f"{GREY}- EnergyPlus is now blocked, waiting on us.{RESET}      ")

            # ---------- 3. the three read tools ----------
            rule("3. the reads that feed one decision - LIVE physics out of EnergyPlus", AQUA)
            state = await call(session, "get_building_state", slow=args.slow)
            goals = await call(session, "get_goals_and_constraints", slow=args.slow, limit=args.limit)
            history = await call(session, "get_recent_history", {"hours": 6},
                                 slow=args.slow, limit=args.limit)

            # ---------- 4. the assembled prompt ----------
            if args.show_prompt:
                from abms.controllers.llm_agent import build_user_prompt, load_system_prompt
                sys_p, usr_p = load_system_prompt(), build_user_prompt(state, goals, history)
                rule("4. what actually goes to the LLM (assembled from those 3 responses)", BLUE)
                print(f"  {GREY}system prompt {len(sys_p):,} chars (~{len(sys_p)//4:,} tokens){RESET}")
                print(f"  {GREY}user prompt   {len(usr_p):,} chars (~{len(usr_p)//4:,} tokens){RESET}")
                print(f"  {GREY}{'-'*60}{RESET}")
                head = usr_p if args.full_prompt else usr_p[:900] + "\n  ..."
                for ln in head.splitlines():
                    print(f"  {WHITE}{ln}{RESET}")
                print(f"  {GREY}{'-'*60}{RESET}")
                print(f"  {AQUA}Every number in there came out of EnergyPlus "
                      f"milliseconds ago.{RESET}")
                if args.slow:
                    await asyncio.sleep(args.slow * 2)

            # ---------- 5. the write, and the guardrail ----------
            if args.provoke_clamp:
                rule("5. set_zone_setpoints() - the write tool, and the guardrail layer", RED)
                bad = {"heating_c": args.bad_heating, "cooling_c": args.bad_cooling,
                       "reasoning": "Deliberately out-of-bounds request, to show the "
                                    "guardrail layer clamping it."}
                print(f"  {RED}Requesting an unsafe setpoint on purpose: "
                      f"heating={bad['heating_c']} cooling={bad['cooling_c']}{RESET}")
                res = await call(session, "set_zone_setpoints", bad, slow=args.slow)
                applied, notes = res.get("applied") or {}, res.get("guardrail_notes") or []
                print()
                if notes:
                    print(f"  {INVERT}{RED} CLAMPED {RESET}  "
                          f"requested {bad['heating_c']}/{bad['cooling_c']}"
                          f"  ->  applied {BOLD}{applied.get('heating_c')}/"
                          f"{applied.get('cooling_c')}{RESET}")
                    for n in notes:
                        print(f"    {YELLOW}! {n}{RESET}")
                    print(f"\n  {AQUA}The model asked for that. The guardrails allowed "
                          f"this. Deterministic, and logged.{RESET}")
                else:
                    print(f"  {GREY}No clamp fired - the request was already in bounds. "
                          f"Try --bad-heating 30 --bad-cooling 12.{RESET}")

            rule("done - this was real MCP traffic against a real EnergyPlus run", GREY)
            print(f"{GREY}  artifacts: {OUT_DIR}{RESET}\n")


def _wrap(text, w):
    words, line, out = text.split(), "", []
    for word in words:
        if len(line) + len(word) + 1 > w:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return out or [""]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slow", type=float, default=0.0,
                    help="seconds to pause after each call, so the camera can keep up")
    ap.add_argument("--limit", type=int, default=24,
                    help="max JSON lines to print per response (default 24; 0 = all)")
    ap.add_argument("--show-prompt", action="store_true",
                    help="also print the prompt assembled from the tool responses")
    ap.add_argument("--full-prompt", action="store_true", help="print the whole prompt")
    ap.add_argument("--provoke-clamp", action="store_true",
                    help="submit an out-of-bounds setpoint to show a live guardrail clamp")
    ap.add_argument("--bad-heating", type=float, default=30.0)
    ap.add_argument("--bad-cooling", type=float, default=12.0)
    args = ap.parse_args()
    if args.limit == 0:
        args.limit = None
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print(f"\n{GREY}interrupted{RESET}")


if __name__ == "__main__":
    main()
