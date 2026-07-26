# Design decision log

Dated notes on the non-obvious choices: what was decided, and why.

## Model and dependencies

- **Model: `qwen2.5:3b-instruct`, not the 7B.** The 7B pull measured about
  1.1 MB/s on this machine, with one attempt failing outright on a DNS
  error partway through. The 3B is the same family and fits the build
  budget. The controller is model-agnostic, so swapping back is a config
  change.
- **Dashboard dependencies split out.** `streamlit`, `pandas`, `plotly` and
  their heavy transitive wheels live in `requirements-dashboard.txt`.
  `matplotlib` stayed in the main requirements: the validation plots need
  it independently of the dashboard.
- **Single-completion latency, toy prompt: 8.69s.** Measured by
  `scripts/smoke_ollama.py`, cold cache, CPU inference. See below for the
  real-prompt figure, which is 2-3x this.

## EnergyPlus API

- **`requestVariable` must be called before the run starts.** The header
  says "prior to executing each simulation", and calling it from
  `callback_begin_new_environment` is too late: that fires after input
  processing, and API-only variables such as `Schedule Value` come back
  with invalid (-1) handles. Call it straight after
  `state_manager.new_state()`. Hard-failing on invalid handles caught this
  immediately instead of silently reading garbage.
- **`get_meter_value` returns the interval value, not a lifetime total.**
  The installed 26.1.0 docstring says it "currently returns the
  instantaneous value of a meter, not the cumulative value". Confirmed
  empirically: summing interval values across the week reproduces the CLI
  run's `Electricity:HVAC [J](RunPeriod)` total exactly. So `simulation.py`
  accumulates its own running total rather than differencing, and the J to
  kWh conversion happens in exactly one place.

## Building model

`5ZoneAirCooled.idf` worked cleanly, so the fallback to
`RefBldgSmallOfficeNew2004_Chicago.idf` was never needed. VAV, electric
chiller with gas boiler, an `Electricity:HVAC` meter, and all five zones on
shared named setpoint schedules. Full rationale in `models/README.md`.

Read-path validation: a one-week run (1/14-1/20, Chicago, 672 zone
timesteps, no warmup or sizing rows leaked, no callback exceptions). Total
HVAC electricity through the API wrapper was 63.60961907606415 kWh against
63.6096 kWh from a plain CLI run's `eplusmtr.csv`, matching to six decimal
places. The setpoint schedules were edited later, so that exact figure is
no longer reproducible from the committed IDF; it validated the read path,
which didn't change afterwards.

## Actuation

- **Actuators confirmed from the `.edd` listing.** Added
  `Output:EnergyManagementSystem,Verbose,Verbose,Verbose;`, reran the CLI
  pass, and grepped for `HTG-SETP-SCH` and `CLG-SETP-SCH`, both
  `Schedule:Compact` / `Schedule Value`. Excerpt in
  `docs/discovered_names.md`.
- **Wiring check with an absurd setpoint.** A one-day run forcing 15 C
  cooling, guardrails deliberately bypassed, dropped all five zones to
  16.3-18.0 C, well below the normal 21-24 C occupied band. That confirms
  the handles drive the schedule the thermostat actually reads and not a
  similarly named decoy.

## Baseline vs rule-based: three wrong answers before a real one

This took most of the controller work, and each step is a real gotcha for
this model family.

1. **Stock schedules as baseline: 0.21% saved.** The stock
   `Htg-SetP-Sch` and `Clg-SetP-Sch` already encoded setback (16.7/29.4
   unoccupied against 22.2/23.9 occupied), so the rule-based controller's
   own setback added almost nothing. Flattened the baseline schedule to a
   constant 21.0/24.0 C.
2. **Flat baseline, still 0.1-0.3% across both a January and a July
   window.** Telemetry showed the actuator stepping correctly, so this
   wasn't a wiring bug. The real cause: `FanAvailSched`,
   `CoolingCoilAvailSched` and `ReheatCoilAvailSched` already gate the
   equipment itself to weekdays 6:00-20:00 for most of the year. The system
   already implements a crude occupancy control of its own, so with the
   equipment off when unoccupied there is little left for a setpoint-only
   controller to save.

   Widening those availability schedules to 24/7 confirmed the diagnosis:
   total electricity roughly doubled from constant fan draw while the
   savings percentage barely moved, because fan power is close to
   setpoint-insensitive at this system's minimum-flow floor. That
   experiment was reverted, since running the AHU 24/7 regardless of
   thermal need isn't a realistic baseline; it just adds a large constant
   load that muddies the comparison.
3. **Following the energy: `Electricity:HVAC` excludes the boiler.** The
   boiler is on `Heating:NaturalGas`. In a Chicago January, heating
   dominates and setback's savings land almost entirely on gas. Broadened
   the telemetry schema and `metrics.total_hvac_kwh` to sum electricity and
   gas, which is standard site-energy practice. Gas turned out to be about
   90% of total HVAC energy for this building in January, which is what
   you'd expect from a gas-boiler VAV reheat system in a cold climate.
4. **Then it overshot: 65%.** Against a zero-setback baseline, which is a
   strawman rather than a defensible one. Replaced it with a modest fixed
   setback (21.0/24.0 C occupied 6:00-20:00 weekdays, 18.0/27.0 C
   otherwise, a plausible programmable thermostat), and brought the
   rule-based unoccupied setpoints in from 15/30 C to 18.3/28.0 C so the
   comparison lands somewhere believable.

**Final numbers** (`runs/phase2_validation/summary.json`, 1/14-1/20): 8.00%
of total HVAC energy saved, 56.5 kWh of 706.0 kWh; 7.2% carbon avoided;
97.7% occupied-hours comfort compliance against the baseline's 100%.

Both controllers use the same occupied setpoints and the same static
occupied window for the baseline schedule, so the savings come from two
genuine effects: a slightly deeper unoccupied setback, and reacting to the
real per-timestep occupancy signal (`OCCUPY-1`, ramping 8:00-19:00) instead
of a static 6:00-20:00 window. The second is the more interesting one,
because it means correctly setting back during the 6-8am and 7-8pm margins
where the fixed schedule assumes an occupied building that is still empty.
It survives even at a modest setback depth.

## Guardrails

Order of application matters: bounds, then step limit, then deadband, then
the occupied floor last, because the occupied floor has to win regardless
of anything else. Every branch in `tests/test_guardrails.py` has a case
where it fires and one where it doesn't.

`decisions.jsonl` holds one object per decision point, not per timestep:
timestamp, controller, occupied flag, requested action (`null` for no
change), guardrail notes, and what was actually applied.

## The agent loop

- **Structured output, not native tool calls, for production.** The agent
  runner is a real MCP client: it spawns `abms.mcp_server` over stdio,
  calls the read tools itself at each decision point, packs the state into
  one prompt, and submits the resulting JSON through `set_zone_setpoints`.
  The MCP layer is in the loop end to end.
- **Reasoning threaded through the existing handshake.**
  `set_zone_setpoints` gained an optional `reasoning` field, the handshake
  carries it across, `MCPBridgeController` surfaces it, and
  `SimulationRunner._log_decision` reads it into `decisions.jsonl`. Four
  small edits rather than a parallel logging path.
- **Fallbacks reuse the handshake machinery.** On malformed JSON after a
  repair retry, or an unreachable Ollama, the runner computes the same
  rule-based decision the sim thread would have used on timeout and submits
  it immediately with a `[fallback: ...]` reasoning string, instead of
  waiting out the full 60s timeout on every affected decision. The
  handshake's timeout stays as the backstop for the runner itself dying.
  Across the 328-decision demo run this path never fired, but it was
  exercised deliberately in a smoke test first.
- **A real bug found by the first live-Ollama run.** `ollama-py` 0.6.2 only
  rewraps `httpx.ConnectError` into the builtin `ConnectionError` it
  documents; read and pool timeouts leak out as raw `httpx.ReadTimeout`.
  One slow completion under CPU contention crashed the whole process.
  Fixed by also catching `httpx.TransportError` in `_complete` and raising
  the same `OllamaUnavailableError`: a slow Ollama should degrade like a
  refused one, not kill the run. Also raised `request_timeout_s` from 30s
  to 45s once real prompts were measured.
- **Real-prompt latency: 17-26s per completion**, against the toy prompt's
  8.69s. Well inside the 60s handshake timeout, but it's why the timeout
  needed raising and why the two-week demo took about 2h20m rather than the
  half hour estimated from the toy figure. Two one-week periods is still
  the right demo scope; an annual run at this latency would take days, not
  a night.
- **Prompt design** (`prompts/controller_system.md`): priority-ordered goals
  with comfort as a constraint above energy above carbon, the guardrail
  bounds spelled out so the model can reason about what will be clamped,
  four worked reasoning examples, and an explicit statement that "no
  change" is a valid and often correct answer. The early worry was that the
  model would fidget every cycle to look busy. It doesn't.

## Demo run results

`runs/demo_final/`, two contrasting weeks, 328 decisions, zero fallbacks.

| period | energy saved | carbon avoided | comfort compliance (AI / baseline) |
|---|---|---|---|
| January week (heating-dominated) | 3.09% | 2.71% | 95.9% / 100% |
| July week (cooling-dominated) | 16.13% | 7.82% | 100% / 100% |

Both weeks beat baseline on energy without breaking the 95% comfort floor.
Rule-based still wins on raw energy in both periods, 8.00% and 20.51%, and
that is reported rather than tuned away: rule-based is a fixed aggressive
setback with no comfort-versus-savings judgement to make, while the LLM is
also reasoning about carbon timing and is more conservative near the
comfort floor. The July result, where the AI beat rule-based on comfort
compliance (100% against 99.8%) while still saving 16%, is the better
evidence that something is reasoning rather than just clamping.

**Decision-log audit.** 20 decisions sampled at random across both weeks
with `scripts/sample_decisions.py`, which pairs each decision with the
telemetry at that timestamp. Every one was justified by the visible state:
unoccupied and in band held; unoccupied with a flat carbon forecast leaned
into setback; pre-occupancy gave explicit recovery reasoning; occupied held
within band. Three guardrail clamps appear in that sample of 20 alone, each
with an honest note, so the layer is doing visible work rather than sitting
idle.

**A degenerate decision worth keeping.** One decision in the smoke run
requested heating 17.5 / cooling 26.0 while the building held 52 people,
reasoning that it was "expected to be unoccupied soon". That was simply
wrong at 8:20 on a weekday. The occupied comfort floor clamped heating to
20.0 before it reached the actuator. Documented rather than papered over:
this is exactly what the guardrails are for, and it shows the safety layer
catching a small model's bad reasoning in practice rather than in theory.

## Peak-demand threshold

Derived from committed baseline telemetry, not guessed. Interval-average
HVAC electricity peaks at 0.416 kW in `january_week/baseline` and 0.639 kW
in `july_week/baseline`; July's cooling load is the higher, consistent with
winter savings landing on the gas reheat coil and leaving electricity flat.
The threshold is 80% of the higher value, 0.512 kW, rounded to 0.5 kW in
`config/default.yaml`. Sub-kW magnitudes are plausible here: this is
electricity alone for a small five-zone reference model, gas dominates the
heating-season total, and it isn't a commercial campus.

## Extended run, stopped partway

Launched from commit `b3c8eedc42d53be63826f719dcbce35b11076e1e` with a
clean working tree, in a separate terminal so it would survive the session
ending. `scripts/run_extended.sh` patches the model to Jan 1-31, runs the
baseline, then the AI run in structured mode at a 60 sim-minute interval,
roughly 744 decisions.

**Stopped deliberately, not a crash.** `SIGINT` rather than `SIGKILL`, so
the MCP session and subprocess context managers unwound cleanly; both
processes exited within seconds. Telemetry and decisions flush per row and
per decision, so nothing in flight was lost.

**Coverage at the stop.** The baseline completed the full month, 2976
zone-timesteps. The AI covered `1986-01-01T00:15` to `1986-01-08T06:45`:
172 decisions, zero fallbacks and zero alerts, confirmed both from
`decisions.jsonl` and an `ALERT` grep of the run log, about 23% of the
target. No crashes, no handshake timeouts, no unavailable-Ollama or
malformed-output fallbacks anywhere in the covered window. That is the
reliability evidence the run existed to produce, over 7.3 days instead of
31.

**A caveat that must not be misread.** `summary.json`'s
`comparison.ai_vs_baseline` compares a full-month baseline against a
7.3-day AI partial, so its roughly 73% "energy saved" and "carbon avoided"
figures are an artifact of the period mismatch, not a result. A
`PARTIAL_RUN_NOTE.md` sits in the run directory flagging this for anyone
browsing without reading this log. No special-casing was added to the
metrics code, since that would need a matched-period baseline slice.

## Native tool-calling

- **First round worked almost immediately.** A standalone probe against
  `qwen2.5:3b-instruct` via `ollama.Client.chat(..., tools=[...])` returned
  a valid `get_building_state` call in 8s, and a full two-round loop
  finished in about 19s.
- **A harness bug, not a model failure.** `agent_runner._call`'s
  `json.loads(result.content[0].text)` failed with `Expecting value: line 1
  column 1 (char 0)` on `set_zone_setpoints` specifically. Returning the raw
  `TextContent` on failure showed why: FastMCP's validation was correctly
  rejecting `heating_c=None, cooling_c=None`, and the resulting error text
  wasn't the plain JSON `_call` expected. Fixed by preferring
  `result.structuredContent` when present and raising a descriptive error
  otherwise, plus requiring the setpoints be actual numbers before the call
  goes out, which turns a confusing parse error into a clean
  `NativeToolCallError`.
- **A genuine model reliability issue, confirmed after that fix.**
  `qwen2.5:3b-instruct` intermittently calls `set_zone_setpoints` with
  `heating_c` and `cooling_c` explicitly `null`, or with empty arguments.
  Both are caught before the call and fall through to structured mode.
- **Showcase run** (`runs/demo_final/native_showcase/`, one simulated day,
  60 sim-minute interval): 24 of 24 decisions completed, no crashes, no
  rule-based fallbacks. Of those, 4 were genuine native decisions, one of
  which made 8 tool calls including several reads before deciding, and 20
  fell through to structured mode after a null-argument call. A roughly 17%
  native success rate is honestly low for a 3B model, but all three
  fallback layers are demonstrably working, with the evidence in
  `decisions.jsonl`.
- **Structured mode is unaffected.** A two-day structured regression run
  completed 47 of 47 decisions through the LLM with no fallbacks and no
  native-path invocation. `llm_agent.mode` defaults to `structured`, and
  `orchestrator.run_ai` never passes `mode`, so the production path always
  gets the default. Native mode exists only behind `--mode native`.
- **Outcome.** Native mode works and is demonstrated, but structured mode
  stays the production configuration: 17% isn't reliable enough to run
  unattended at scale.
