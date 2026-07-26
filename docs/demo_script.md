# Demo video script  -  recording runbook

Target: **<= 3:00**, six beats. This file is the single source of truth for
recording the PoC video  -  narration text, exact commands, expected output,
and timing per beat. `scripts/run_demo.sh` mirrors the commands below so the
exact sequence used in the video is committed and re-runnable.

## Beat budget  -  the live loop is the video

The brief asks for "the loop in action  -  data transferring live from
EnergyPlus to the LLM and the subsequent control actions updating the model
parameters automatically." Beats 3 and 4 are that, and together they own
**2/3 of the runtime**. Everything else is compressed to serve them.

| Beat | Window | Length | Cuttable? |
| --- | --- | --- | --- |
| 1 - Hook | 0:00-0:12 | 12s | no |
| 2 - Architecture | 0:12-0:30 | 18s | trim to 10s |
| **3 - LIVE LOOP (split screen)** | **0:30-1:50** | **80s** | **never  -  this is the deliverable** |
| **4 - TOOL-CALL TRACE + live clamp** | **1:50-2:38** | **48s** | **never** |
| 5 - Dashboard | 2:38-2:52 | 14s | **cut this first** if you overrun |
| 6 - Close | 2:52-3:00 | 8s | no |

If you are over 3:00, cut beat 5 entirely and trim beat 2  -  the dashboard is
a static artifact you can also show in the slides; the live loop is not.

Recording tool: QuickTime Player (macOS) -> File -> New Screen Recording.
Record at 1080p+. Enlarge the terminal font before you start (`Cmd+=`
repeatedly, aim for ~20pt) so text reads on camera.

---

## 0. Pre-flight checklist (before you press record)

Run every line below in the terminal you'll record beat 3 in, so the
environment is warm and you're not debugging on camera.

```bash
cd /Users/kanadb/Work/autonomous-building-optimisation-energyplus
source .venv/bin/activate

# REQUIRED: `abms` lives in src/ and is not pip-installed, so `python -m
# abms.agent_runner` fails with ModuleNotFoundError without this. Must be
# exported in every pane you run a beat-3 command in.
export PYTHONPATH="$PWD/src"
python -c "import abms"   # should print nothing

# Confirm the model is present and warm it (first inference after a cold
# load is slow -- do this before recording so beat 3's first cycle isn't stalled)
ollama list | grep qwen2.5:3b-instruct
ollama run qwen2.5:3b-instruct "hi" >/dev/null

# Confirm EnergyPlus + Ollama are both reachable
python scripts/smoke_energyplus_api.py
python scripts/smoke_ollama.py

# Confirm dashboard deps are installed
python -c "import streamlit, pandas, plotly" || uv pip install -r requirements-dashboard.txt

# Beat 4: prove the tool-call tracer runs clean BEFORE you record. It spawns
# its own mcp_server + EnergyPlus (~20-40s to start), so rehearse it once.
python scripts/tool_call_trace.py --provoke-clamp --limit 6 2>/dev/null | tail -20
rm -rf runs/tool_trace/     # throwaway; re-created on the take

# Confirm the repo state you'll show is the one you intend to tag afterward
git status --short
git log --oneline -1
```

Other prep:
- Close Slack/email/anything that can pop a notification banner mid-recording.
- Quit other apps competing for CPU  -  beat 3's ~17-26s/decision latency
  assumes a mostly-idle machine; a busy machine makes it slower on camera.
- Have three windows/tabs ready to switch between: (a) the architecture
  diagram rendered (VS Code preview, or push to GitHub and view there), (b)
  the split-screen terminal for beats 3 and 4, (c) a browser tab for the
  Streamlit dashboard (don't launch it yet  -  launching live is part of
  beat 5's footage, if you get there).
- **Pane plan for beats 3 + 4** (set this up once; both beats use it):
  left ~60% = the live `agent_runner`; right-top = `tail -f` on
  `telemetry.csv`; right-bottom = free, used for beat 4's tool-call trace.
- Decide now whether you're screen-recording full-screen or a cropped
  window; keep it consistent across beats so cuts don't jump-scale.

---

## 1. Title / hook  -  0:00-0:12

**On screen:** `docs/architecture.md`'s component diagram (top of the file),
rendered, full screen.

**Say:**
> "A local, open-source LLM autonomously operates a simulated office
> building  -  EnergyPlus for the physics, Ollama for the reasoning, connected
> over MCP."

No commands needed  -  this is a static view of the rendered diagram.

---

## 2. Architecture walkthrough  -  0:12-0:30

**On screen:** same diagram; move the cursor along the arrows as you narrate
(EnergyPlus -> SharedState -> MCP server -> agent runner -> LLM -> guardrails ->
back to EnergyPlus).

**Say:**
> "EnergyPlus streams zone temperatures and occupancy into a shared state.
> The MCP server exposes that as tools. The LLM reads it and proposes
> setpoints. Every proposal passes through a deterministic guardrail layer
> before EnergyPlus ever applies it  -  that's the safety net, and it's not
> negotiable by the model."

Optional: scroll to the sequence diagram just below it for 2-3 seconds if
time allows  -  skip it if you're tight, beat 3 shows the same cycle live.

---

## 3. Live loop  -  THE MONEY SHOT  -  0:30-1:50 (80s)

This is the one live piece of footage in the whole video: real EnergyPlus
state flowing into a real LLM call flowing into a real guardrail-checked
actuation, all happening while the camera is rolling. Everything else in the
video can be a pre-existing artifact; this beat cannot  -  run it live.

> **Do not record a replay.** `runs/demo_final/` contains real logs, and it
> is technically easy to tail them into two panes and narrate over it. Don't.
> The brief asks for the loop *in action*; a replay presented as live is
> fabricated evidence, and this project's credibility rests on reporting
> results honestly  -  including that the rule-based controller out-saves the
> LLM in January. Record the real thing; 3.0 makes that easy.

### 3.0 Start early, record late (the dead-air fix)

The run starts at sim 00:15 and occupancy (`OCCUPY-1`) begins ~08:00. At one
decision per 60 sim-minutes and ~20s each, the interesting occupancy-transition
reasoning is **eight decisions  -  roughly 2.7 minutes  -  away**. Everything
before it is "no zones occupied, hold setpoints."

So: **start the run before you press record.** Let the sim clock reach ~06:00,
then start recording. Both panes will already carry real scrolling history,
and the good decisions arrive within the first few on-camera cycles. This is
one continuous live run  -  you are choosing when to press record, which is
ordinary filmmaking, not staging.

### 3.1 The exact command

Run this yourself, in the recording window, once you've hit record:

```bash
python -m abms.agent_runner \
  --idf models/building.idf \
  --epw models/weather/USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw \
  --run-id demo_video \
  --output-dir runs/demo_video/ai \
  --period-days 7
```

This spawns `abms.mcp_server` as a stdio subprocess (real EnergyPlus C-API
callbacks driving the sim thread) and starts polling it as an MCP client
identical code path to every other run in this repo, nothing mocked or
canned for the video.

### 3.2 Split-screen layout  -  what goes where

One terminal alone only shows the LLM's *side* of the loop (a decision every
~20s). To make the EnergyPlus->LLM data transfer itself visible  -  not just
the outcome  -  split the recorded window into two panes and put a different
half of the loop in each. This is the visual that makes beat 3 read as "live
data transferring," not just "a script printing text."

There is no live-refresh dashboard mode; it was deliberately cut. The
split-screen below is the
substitute, and it's built entirely from files this run already writes, so
nothing extra needs to be built.

| Pane | What | Why |
| --- | --- | --- |
| **Left** (~60% width) | The `agent_runner` command from 3.1, its own stdout | The LLM side: one block every ~20s, `reasoning` -> `requested` -> `applied`. This is what you narrate over. |
| **Right** (~40% width) | `tail -f` on the run's `telemetry.csv` | The EnergyPlus side: one raw row per zone timestep (every 15 sim-minutes  -  4x more often than the 60-minute LLM decision cadence), showing zone temps, occupancy, setpoints, and HVAC power ticking on their own, independent of whether the LLM has spoken yet. |

Set up (before you hit record, so both panes exist and are correctly sized):

- **Terminal.app / iTerm2:** `Cmd+D` to split the window vertically, left
  pane ~60% width, right pane ~40%.
- Both panes need the venv active and the repo as `cwd`, and the left pane
  needs `PYTHONPATH` (see 0; without it the runner dies immediately with
  `ModuleNotFoundError: No module named 'abms'`):
  ```bash
  source .venv/bin/activate       # run in BOTH panes
  export PYTHONPATH="$PWD/src"    # left pane at minimum; harmless in both
  ```

Start order matters  -  the left pane creates `runs/demo_video/ai/telemetry.csv`
on startup, so the right pane's `tail -f` has nothing to follow until the
left one has run for a second or two:

1. **Left pane:** start the 3.1 command first.
2. Wait for `[agent_runner] session initialized ...` to print (confirms
   `telemetry.csv` now exists).
3. **Right pane:**
   ```bash
   tail -f -n 0 runs/demo_video/ai/telemetry.csv
   ```
   (`-n 0` skips the header-only backlog and starts from whatever's written
   next, so the first thing that appears on the right is a live row, not a
   stale header.)

What the right pane's rows look like (one per zone timestep, appended and
flushed immediately  -  `TelemetryLogger.append`, `src/abms/telemetry.py`):

```
1994-01-14T08:15:00,demo_video,mcp,21.3,21.1,20.9,21.4,21.2,3,2,0,4,1,20.4,21.0,24.0,0.184,12.6,0.0,58.2
```

Columns (left to right): `timestamp, run_id, mode`, five `zone_temp_c_*`
columns, five `zone_occupant_count_*` columns, `outdoor_temp_c,
heating_setpoint_c, cooling_setpoint_c, hvac_electricity_interval_kwh,
hvac_electricity_cumulative_kwh, hvac_gas_interval_kwh,
hvac_gas_cumulative_kwh`. Don't read column-by-column on camera  -  the point
is the visual cadence, not the numbers: point at the right pane and note
that new rows keep landing between LLM decisions, then point at the left
pane's `heating_c=`/`cooling_c=` values and note they match the right
pane's `heating_setpoint_c`/`cooling_setpoint_c` in the row immediately
after a decision applies  -  that's the "control action updating the model
parameter" moment, visible as a value change in a file EnergyPlus itself is
reading from, not just asserted by the narration.

**Say, gesturing left->right->left:**
> "On the left, the LLM checking in every sixty simulated minutes. On the
> right, EnergyPlus itself  -  ticking every fifteen minutes independent of
> whether the model has decided anything yet. Watch the setpoint columns
> update the moment a decision lands  -  that's the control action actually
> reaching the physics engine."

If a two-pane layout isn't practical (e.g. recording a cropped window),
skip the right pane. The left pane's `requested:`/`applied:` line (3.3
below) alone still shows the full decision, just without the visual
EnergyPlus-side cadence next to it.

### 3.3 What appears, in order

First, almost immediately:

```
[agent_runner] session initialized -- run_id=demo_video target~170 decisions
```

Then one block per decision cycle (roughly every **17-26 seconds**
Ollama's measured single-completion latency on this machine, per
`config/default.yaml`), shaped exactly like this:

```
[1994-01-14T08:00:00] occupied=True source=llm
  reasoning: Zones are occupied and near the comfort band; maintaining current
  setpoints since the outdoor temperature is moderate and no pre-conditioning
  is needed.
  requested: heating=21.0 cooling=24.0  applied: heating=21.0 cooling=24.0  guardrail_notes=[]
```

Read left to right, this one block *is* the closed loop:
- `[1994-01-14T08:00:00] occupied=True`  -  EnergyPlus's live sim clock and
  occupancy, read via `get_building_state()` a moment ago.
- `reasoning:`  -  the LLM's own live output for this cycle (not scripted).
- `requested:`  -  what the LLM asked for.
- `applied:`  -  what the guardrail layer actually let through.
- `guardrail_notes`  -  empty here (nothing clamped); beat 5 shows a case
  where it isn't.

### 3.4 Timing math for the 80-second window

At ~20s/decision you get **~4 real cycles** in 80 seconds. Don't stretch it
much past that  -  six near-identical decision blocks read worse than four good
ones, and beat 4 needs its 48 seconds. If a cycle lands mid-sentence, let it
finish; ragged timing is fine, a rushed guardrail moment is not.

### 3.5 What to do while it scrolls

**The single best thing you can catch: a reasoning string that quotes a live
number.** The model routinely writes things like *"...unoccupied, with a
moderate outdoor temperature of **-3.9 C**"*  -  and that figure exists nowhere
except EnergyPlus's `outdoor_temp_c`, read via `get_building_state` seconds
earlier. When one appears:

> point at the right pane's outdoor-temp column, then at the left pane's
> reasoning quoting the same value, and say: *"That number came out of the
> physics engine a moment ago. The model is reading the building, not a
> script."*

That is the clearest possible proof of "data transferring live from
EnergyPlus to the LLM," it needs no extra tooling, and nothing pre-recorded
could fake it. Prioritise catching one of these over anything else in the beat.

- Don't touch the keyboard once it's running  -  just let it print.
- Watch the `reasoning` text as it comes in. The moment one references
  something concrete and demo-worthy  -  occupancy change, outdoor
  temperature, pre-cooling/pre-heating, carbon/peak-demand  -  **stop
  narrating and let the camera hold on that block for 2-3 silent seconds**
  before cutting to beat 4. That block is what judges will actually read
  back, so let it breathe.
- If the first cycle or two are dull ("maintaining current setpoints, no
  change needed"), that's normal  -  don't restart, just wait for a richer one.

### 3.6 Stopping and cleaning up

Once you have your stretch on camera:

```bash
# Ctrl+C in the running terminal  -  you do NOT need the full 7-day run to finish
```

After the whole recording session is done (not mid-take):

```bash
rm -rf runs/demo_video/   # throwaway recording artifact, not runs/demo_final -- do not commit
```

### 3.7 If something goes wrong live

- **`ModuleNotFoundError: No module named 'abms'` immediately:** the pane is
  missing `export PYTHONPATH="$PWD/src"` (see 0). The package is in `src/` and
  is not pip-installed. Note this only affects the pane *you* type in  -  the
  `mcp_server` subprocess sets its own `PYTHONPATH` (`agent_runner.py`), so
  once the parent starts, the child is fine.
- **Ollama is slow/cold and the first cycle stalls past ~45s:** that's the
  configured `request_timeout_s`; the runner will fall back to a rule-based
  decision and print `[agent_runner] ALERT: fallback-...`. Not fatal, but
  re-warm (`ollama run qwen2.5:3b-instruct "hi"`) and restart the beat for a
  cleaner take rather than keeping an ALERT line as your money shot.
- **No output at all after ~10s:** EnergyPlus itself may still be in its
  warmup/sizing pass before the first decision point  -  this is normal
  startup latency, not a hang; give it a few more seconds before assuming
  something broke.
- **You need a second take:** just re-run the same command with a fresh
  `--run-id` (e.g. `demo_video2`) so you don't collide with the previous
  attempt's output directory  -  remember to update the right pane's `tail -f`
  path to match if you're using the 3.2 split-screen layout.
- **Right pane's `tail -f` shows nothing:** almost always means it was
  started before the left pane created `telemetry.csv`  -  `Ctrl+C` it and
  re-run once you see `[agent_runner] session initialized` on the left.

---

## 4. Tool-call trace  -  the MCP wire  -  1:50-2:38 (48s)

Beat 3 shows the loop's *effects*. It cannot show the loop's *mechanism*
the MCP tool calls are in-memory reads and a stdio JSON-RPC exchange, and
they leave no trace on screen. This beat makes them visible, and ends on a
live guardrail clamp.

**Where to run it:** the right-bottom pane (the recording-cue pane; its job
is done by now). `Ctrl+C` the cue watcher and run:

```bash
python scripts/tool_call_trace.py --show-prompt --provoke-clamp --slow 1.5 2>/dev/null
```

`2>/dev/null` is not optional for a clean shot  -  the MCP server logs
`Processing request of type CallToolRequest` to stderr, which interleaves
with the transcript and garbles the layout. (Drop it only if you specifically
want to show that raw request traffic.)

**Leave beat 3's live run going in the left pane** while this runs. Two real
things on screen at once is the point.

### 4.1 What appears, in four movements

```
1 - list_tools()    -  the tool surface the LLM is handed
      get_building_state()          get_recent_history(hours)
      get_goals_and_constraints()   get_performance_so_far()
      set_zone_setpoints(heating_c, cooling_c, reasoning)
      5 tools  -  four read, one write.

2 - polling get_building_state() until EnergyPlus wants a decision
      awaiting_decision=True after 3 polls  -  EnergyPlus is now blocked, waiting on us.

3 - the reads that feed one decision  -  LIVE physics out of EnergyPlus
   > call_tool(get_building_state, {})
   < response in 2 ms
     { "sim_datetime": "1986-01-14T00:15:00", "outdoor_temp_c": -12.6,
       "zones": { "SPACE1-1": { "temp_c": 17.998, "pmv": -1.051 }, ... },
       "current_demand_kw": 0.3673, "awaiting_decision": true }

4 - set_zone_setpoints()  -  the write tool, and the guardrail layer
     CLAMPED   requested 30.0/12.0  ->  applied 21.0/24.0
       ! heating clamped to bounds [12.0, 23.0]: 30.0 -> 23.0
       ! cooling clamped to bounds [22.0, 32.0]: 12.0 -> 22.0
       ! heating step limited to 3.0C/decision: 23.0 -> 21.0
       ! cooling step limited to 3.0C/decision: 22.0 -> 24.0
```

### 4.2 Narration

Over movements 1-3 (~25s):
> "This is the whole interface between the model and the building: five
> tools, four read, one write. Here are the reads that feed a single
> decision  -  live zone temperatures, comfort index, current demand, straight
> out of EnergyPlus. Two milliseconds, because the tools read the simulation
> in-process. The twenty seconds a decision costs is all model thinking."

Over movement 4 (~20s)  -  **slow down here, this is the reliability proof**:
> "Now I'll deliberately ask for something unsafe: heat to thirty degrees
> *and* cool to twelve, simultaneously. Watch  -  it isn't rejected, it's
> clamped: hard bounds first, then the three-degree-per-decision step limit,
> and every clamp logged with its reason. The model asked for that. The
> guardrails allowed this. The LLM never touches the actuators directly."

Then hold silent on the clamp block for 2-3 seconds before cutting.

### 4.3 The one thing you must say out loud

This starts its **own** `mcp_server` + EnergyPlus instance  -  an MCP stdio
server serves exactly one client, so it cannot attach to the run in the left
pane. Say so plainly:

> "Same server, same five tools, same code path  -  a second instance, so we
> can watch the wire."

A judge who knows MCP will wonder; answering before they ask costs three
seconds and buys credibility. Implying it's the same process would be false.

### 4.4 Notes

- **This replaces the old "grep a clamp out of the committed log" beat.**
  Same evidence, happening live, and it can't be accused of cherry-picking.
- Add `--full-prompt` to show the entire assembled prompt (~2,350 tokens)
  instead of the first 900 chars  -  only if the pane is large enough.
- If the clamp doesn't fire, the request was already in bounds:
  `--bad-heating 30 --bad-cooling 12` are the defaults and do fire; the
  guardrail constants are in `src/abms/guardrails.py`.
- Startup takes ~20-40s (EnergyPlus init) before movement 1 appears. **Start
  it during beat 3's last cycle** so it's already at movement 1 when you cut.
- Cleanup after recording: `rm -rf runs/tool_trace/`.

---

## 5. Dashboard tour  -  2:38-2:52 (14s)  -  CUT THIS FIRST IF YOU OVERRUN

Beats 3 and 4 are the deliverable; this is a static artifact that also lives
in the slides. If you are at 2:40 when beat 4 ends, skip straight to the
close  -  nothing is lost.

If you have the time, **launch it live** (start the command as you cut from
beat 4, narrate over the few seconds it takes to open) and show **only** the
stat-tile row and the cumulative-energy chart  -  roughly 7 seconds each:

```bash
streamlit run dashboard/app.py
```

Opens at `http://localhost:8501`. Walk through, in this order, ~10s each:

1. **Stat tiles** (top row): energy saved %, comfort compliance %, CO2
   avoided kg, autonomous decisions made.
   > "Across the AI-controlled run: energy saved, comfort held, carbon
   > avoided, and every one of those decisions made autonomously."
2. **Cumulative energy chart** (baseline vs AI, gap shaded).
   > "The gap between the orange baseline and the blue AI line is the
   > savings, accumulating day over day."
**Skip charts 3 and 4** (comfort/setpoint, carbon/decision feed) unless you
finished beat 4 early  -  beat 3 already showed setpoints tracking occupancy
live, and beat 4 already showed the reasoning. Don't re-tell either.

Stay on one period. Don't burn the clock toggling `january_week` /
`july_week`.

> **Retired:** an earlier version of this script used a beat here that
> grepped an already-proven clamp out of
> `runs/demo_final/extended_january/agent_runner_report.log`. Beat 4 now
> shows a clamp happening live, which is strictly better evidence  -  the grep
> is kept only as a fallback if `tool_call_trace.py` fails on the day:
> `grep -B1 "guardrail_notes=\['" runs/demo_final/extended_january/agent_runner_report.log | head -4`

---

## 6. Close  -  2:52-3:00 (8s)

**On screen:** repo file tree (`tree -L 2` or Finder/VS Code sidebar), then
cut to the README results table.

```bash
tree -L 2 -I '__pycache__|.venv|*.egg-info'
```

**Say:**
> "January: three percent saved by the AI, eight by a simpler rule-based
> controller  -  an honest result, we're not hiding it. July: sixteen percent
> saved, comfort fully held. One building, one climate, for now. Full
> reasoning trace for every decision, in the repo."

Cut.

---

## Post-recording checklist

1. Trim in QuickTime (Edit -> Trim) to <= 3:00; export 1080p.
2. Clean up recording artifacts: `rm -rf runs/demo_video/ runs/tool_trace/`.
3. Tag the commit the video was actually recorded against:
   ```bash
   git add -A
   git commit -m "docs: architecture diagrams, results README, demo script"
   git tag -a v1.0-demo -m "Commit recorded for PoC demo video"
   git push origin main
   git push origin v1.0-demo
   ```
4. Sanity-check the exported file: duration <= 3:00, audio present, terminal
   text legible when played back at normal size (not just while editing).
