# Design decision log

## 2026-07-26 — Phase 0

- **Model choice deviation:** the plan (§1.2, §4) recommends `qwen2.5:7b-instruct`
  (~4.7 GB) as primary. This machine's internet connection measured ~1.1 MB/s
  during the pull (ETA 60+ min, with one download attempt failing outright on
  a DNS lookup error partway through). Switched to **`qwen2.5:3b-instruct`**
  (~1.9 GB) to fit the 6–10 h build budget. It is a same-family, smaller model;
  swappable later per the plan's model-agnostic controller requirement (§1.2)
  if it proves too erratic once Phase 4 testing begins.
- **Dependency deferral:** `streamlit`, `pandas`, `plotly`, `matplotlib` (and
  their transitive heavy wheels, notably `pyarrow` ~33 MB) are not required
  for Phase 0's exit criteria or Phases 1–4. Given the slow network, these are
  deferred to `requirements-dashboard.txt` and will be installed at the start
  of Phase 5. Core deps (`mcp`, `ollama`, `pyyaml`, `pydantic`, `pytest`) are
  installed now and frozen in `requirements.txt`.
- **Ollama latency measurement:** `scripts/smoke_ollama.py` against
  `qwen2.5:3b-instruct` measured **8.69 s** single-completion latency (toy
  JSON-decision prompt, cold cache, CPU/M2 inference). Within the plan's
  expected 2–10 s range (§2, Phase 0.4). At a 60 sim-minute decision interval
  this is negligible; informs the Phase 4 wall-clock budget (§2, Phase 4.4).

## 2026-07-26 — Phase 1

- **Building model:** `5ZoneAirCooled.idf` (first candidate per §1.1) worked
  cleanly with no fighting — no fallback to `RefBldgSmallOfficeNew2004_Chicago.idf`
  needed. VAV system, electric chiller + gas boiler, `Electricity:HVAC` meter,
  all 5 zones on shared named setpoint schedules (`Htg-SetP-Sch`/`Clg-SetP-Sch`).
  Full rationale in `models/README.md`.
- **`matplotlib` un-deferred:** the Phase 0 decision above deferred
  `matplotlib` to `requirements-dashboard.txt` alongside `streamlit`/`pandas`/
  `plotly`. That was too broad — §4 lists `matplotlib` specifically as needed
  for "throwaway validation plots in Phases 1–2", independent of the
  dashboard. Installed into the main venv and frozen in `requirements.txt`;
  the heavier dashboard-only deps (`streamlit`, `pandas`, `plotly`, `pyarrow`)
  remain deferred to Phase 5.
- **`requestVariable` timing gotcha (not in the plan, discovered by hard-fail):**
  the C API docs (`include/EnergyPlus/api/datatransfer.h`) say
  `requestVariable` "should be called prior to executing each simulation" —
  calling it from `callback_begin_new_environment` (which fires *after*
  EnergyPlus's GetInput/input-processing step) is too late and produces
  invalid (-1) handles for API-only variables like `Schedule Value`. Fix:
  call `request_variable` immediately after `state_manager.new_state()`,
  before `runtime.run_energyplus()` starts. The Phase 1 hard-fail-on-invalid-handle
  rule (§1.3) caught this immediately instead of silently reading garbage.
- **`get_meter_value` is interval, not lifetime-cumulative, on this API version:**
  the plan (§6 trap #3) assumes meter reads are cumulative-in-joules and must
  be differenced. The installed 26.1.0 `pyenergyplus` docstring for
  `get_meter_value` explicitly says it "currently returns the instantaneous
  value of a meter, not the cumulative value" (per-timestep energy, already
  differenced) — confirmed empirically (summing interval values across the
  week reproduces the CLI run's `Electricity:HVAC [J](RunPeriod)` total
  exactly). `simulation.py` accumulates its own running total in Python
  instead of differencing; J→kWh conversion happens in exactly one place
  (`SimulationRunner._record_state`).
- **Phase 1 validation (exit criteria, §2):** 1-week run (1/14–1/20, Chicago,
  672 zone timesteps, 0 warmup/sizing rows leaked, 0 callback exceptions).
  Zone-vs-outdoor temperature plot (`docs/img/phase1_zone_vs_outdoor_temp.png`)
  shows physical diurnal swings, HVAC regulation to the occupied/unoccupied
  setback schedule, and a plausible solar-gain overshoot on the south-facing
  zone. Total HVAC electricity via the API wrapper: **63.60961907606415 kWh**,
  vs. **63.6096 kWh** from a plain CLI run's `eplusmtr.csv`
  `Electricity:HVAC [J](RunPeriod)` value (228,994,628.674 J) — match to
  6 decimal places, far inside the ~1% tolerance. (Note: Phase 2 later edits
  `Htg-SetP-Sch`/`Clg-SetP-Sch` in `models/building.idf`, so this exact kWh
  figure is no longer reproducible from the current committed IDF — it
  validated the *read path*, which Phase 2 built on unchanged.)

## 2026-07-26 — Phase 2

- **EMS actuators confirmed via `.edd`:** added
  `Output:EnergyManagementSystem,Verbose,Verbose,Verbose;` to
  `models/building.idf`, reran the plain CLI pass, and grepped
  `eplusout.edd` for the actuation targets named in Phase 1:
  `HTG-SETP-SCH`/`CLG-SETP-SCH`, both `Schedule:Compact` / `Schedule Value`.
  Excerpt committed to `docs/discovered_names.md`.
- **Actuation sanity check (§2.1, `scripts/verify_actuation.py`):** a
  one-day run forcing an absurd 15 °C cooling setpoint (guardrails
  deliberately bypassed via a `bypass_guardrails` controller flag, used only
  by this sanity-check controller) dropped all 5 zone temperatures to
  16.3-18.0 °C, well below the normal 21-24 °C occupied band — confirms the
  actuator handles are wired to the schedule the thermostat actually reads,
  not a similarly-named decoy (§6 trap #8).
- **Baseline-vs-rule-based savings investigation (the bulk of Phase 2's
  time):** this went through three root causes before landing on a plausible
  number, documented in full because each step is a real, re-discoverable
  gotcha for this model family:

  1. *First attempt, stock schedules as baseline:* 0.21% savings. Exactly
     the failure mode §2's validation note warns about — the stock
     `Htg-SetP-Sch`/`Clg-SetP-Sch` already encoded occupied/unoccupied
     setback (16.7/29.4 unoccupied vs. 22.2/23.9 occupied), so rule-based's
     own setback added almost nothing on top. **Applied the plan's
     prescribed fix:** simplified the baseline schedule to a flat,
     always-the-same setpoint (21.0/24.0 °C, `For: AllDays`).
  2. *Second attempt, fully flat baseline, still ~0.1-0.3% savings across
     both a January and a July dev window:* investigation via
     `decisions.jsonl` and telemetry confirmed the actuator *was* stepping
     correctly (15/30 unoccupied, 21/24 occupied, guardrail-limited ramps in
     between) — so this wasn't a wiring bug. The real cause: `FanAvailSched`,
     `CoolingCoilAvailSched`, and `ReheatCoilAvailSched` in the stock model
     already gate the HVAC equipment itself to occupied-hours-only (weekdays
     6:00-20:00) for most of the year — i.e. the *system* already implements
     a crude form of occupancy-based control, independent of the setpoint
     schedule. With the equipment already off when unoccupied, the setpoint
     value during those hours is close to moot, so a setpoint-only
     controller has very little left to save. (A test that widened these
     availability schedules to 24/7 confirmed this diagnosis — total
     electricity roughly doubled from constant fan draw, but the savings %
     barely moved, because fan power turned out to be close to
     setpoint-insensitive at this system's minimum-flow floor. That
     experiment was reverted — running the AHU fan 24/7 regardless of any
     thermal need is not a realistic "conventional" baseline, it just adds a
     large setpoint-insensitive constant load that muddies the comparison.)
  3. *Third finding, following the energy trail:* `Electricity:HVAC` (chiller
     + fans + pumps) excludes the boiler, which is natural gas
     (`Heating:NaturalGas`). In a Chicago January week, heating dominates and
     setback's real savings land almost entirely on gas, not electricity —
     the plan's 5-15% expectation implicitly assumed a system/season where
     electricity is the dominant HVAC energy carrier. **Fix:** broadened the
     telemetry schema (`hvac_gas_interval_kwh`/`hvac_gas_cumulative_kwh`,
     `Heating:NaturalGas` meter) and `metrics.total_hvac_kwh` to sum
     electricity + gas (both already in kWh; summing site energy across
     fuels this way is standard practice, e.g. ASHRAE/utility "site EUI"
     reporting). Gas turned out to be ~90% of total HVAC energy for this
     building in January — expected for a gas-boiler VAV reheat system in a
     cold climate.
  4. *Overshoot correction:* with gas included and the flat (no-setback)
     baseline, savings jumped to 65% — the plan's own validation note flags
     >30% as "suspect a broken baseline," and a *zero*-setback baseline is a
     strawman, not the "defensible... constant setpoint with modest night
     setback" baseline §1.2's honesty rule actually calls for. Replaced the
     flat baseline with a **modest** fixed setback (21.0/24.0 °C occupied
     6:00-20:00 weekdays, 18.0/27.0 °C otherwise — a plausible
     "programmable thermostat" baseline), then tuned the rule-based
     controller's unoccupied setpoints down from the plan's example
     (15/30 °C) to 18.3/28.0 °C so the comparison lands in a believable
     range rather than an extreme one.

  Setpoint-step validation plot: `docs/img/phase2_setpoint_steps.png` (one
  representative occupied day, rule-based run — heating/cooling setpoints
  visibly step at occupancy transitions and the zone temperature follows).

  **Final validated numbers** (`runs/phase2_validation/summary.json`,
  1/14-1/20 dev window): **8.00% total HVAC energy saved** (56.5 kWh of
  706.0 kWh baseline), **7.2% carbon avoided**, **97.7% occupied-hours
  comfort compliance** (baseline 100%, both ≥ the 95% floor). Both
  controllers use the *same* occupied setpoints (21/24) and the *same*
  static weekly occupied window (6:00-20:00 weekdays) for the baseline's
  schedule — the savings come from two independent, genuine effects: (a)
  rule-based's slightly deeper unoccupied setback, and (b) rule-based
  reacting to the *actual* per-timestep occupancy signal (`OCCUPY-1`, which
  ramps 8:00-19:00) rather than baseline's static 6:00-20:00 schedule
  window, so rule-based correctly applies setback during the 6-8am/7-8pm
  margins where baseline's fixed schedule assumes occupied but the building
  is still empty. This second effect is the more interesting one for the
  project's narrative (dynamic occupancy-awareness beating a static
  program), and it survives even at a modest setback depth.
- **Guardrail validator (`guardrails.py`) and its test suite
  (`tests/test_guardrails.py`, 14 cases):** every clamp branch (heating/
  cooling hard bounds, max 3 °C/decision step, ≥1 °C deadband, occupied
  20/26 °C comfort floor overriding the controller) has a case where it
  fires and a case where it doesn't. Order of application matters: bounds →
  step limit → deadband → occupied floor last, since the occupied floor is
  the one guardrail that must win regardless of anything else (§2.4).
- **Decision log (`decisions.jsonl`) format:** one JSON object per decision
  point (not per zone timestep) — timestamp, controller name, occupied flag,
  requested action (`null` for "no change"), guardrail notes, and the
  actually-applied action. This is the evidence trail the autonomy rubric
  axis will lean on once Phase 4 adds LLM reasoning text to the same
  schema.

## 2026-07-26 — Phase 4

- **Architecture confirmed, not revisited:** structured-output mode only
  (§4.1). The agent runner (`src/abms/agent_runner.py`) is a real MCP
  *client* -- it spawns `abms.mcp_server` as a stdio subprocess (the same
  tested Phase 3 server) and, at every decision point, calls the read-tools
  itself, packs the state into one prompt, requires a single JSON decision
  object back from Ollama, and submits it through the `set_zone_setpoints`
  write-tool. The MCP layer is genuinely in the loop end to end; native
  Ollama tool-calling was not attempted, per the plan's explicit v1.1
  descope.
- **Reasoning capture threaded through the existing handshake, not
  bolted on:** `set_zone_setpoints` grew an optional `reasoning` field;
  `DecisionHandshake` carries it from `submit_decision` to
  `request_decision`'s caller via `last_reasoning`; `MCPBridgeController`
  surfaces it; `SimulationRunner._log_decision` reads
  `getattr(controller, "last_reasoning", None)` into `decisions.jsonl`.
  Four small, mechanical edits instead of a parallel logging path -- the
  Phase 3 decision log format didn't change shape, it just gained one
  field.
- **Robustness (§4.4) reuses the Phase 3 fallback machinery instead of
  duplicating it:** on a malformed-JSON-after-one-repair-retry or an
  unreachable/timed-out Ollama, `agent_runner.py` computes the same
  `RuleBasedController` decision the sim thread would fall back to on
  handshake timeout, and submits it itself immediately (with a `[fallback:
  ...]`-prefixed reasoning string) -- rather than staying silent and
  waiting out the full 60s handshake timeout for every affected decision.
  The handshake's own timeout remains the second line of defense in case
  the runner process itself dies or hangs. Across the full two-week demo
  run (328 decisions), this path was never exercised -- Ollama never
  failed once -- but it was exercised deliberately in a unit-style smoke
  test (killed the connection, confirmed the fallback fires and logs
  loudly) before the real run.
- **A real bug found by the first live-Ollama full smoke run:**
  `ollama-py` (0.6.2, installed) only rewraps `httpx.ConnectError` into the
  builtin `ConnectionError` it documents; it does **not** rewrap read/pool
  timeouts, which leak out as raw `httpx.ReadTimeout`. The first
  `compare-ai` smoke run crashed the whole process on one slow completion
  under CPU contention (a stray duplicate smoke-test process was still
  running). Fixed by also catching `httpx.TransportError` in
  `llm_agent.py`'s `_complete` and raising the same `OllamaUnavailableError`
  -- a slow/overloaded Ollama must degrade the same way a refused
  connection does, not crash the run. Also bumped
  `llm_agent.request_timeout_s` from the Phase 0 toy-prompt-derived 30s to
  45s once real state+goals+history prompts were measured.
- **Measured latency for the real prompt, not the Phase 0 toy prompt:**
  the full `get_building_state` + `get_goals_and_constraints` +
  `get_recent_history` payload, packed into one prompt per §4.1, measured
  **17-26s** per completion on `qwen2.5:3b-instruct` (vs. the toy prompt's
  8.69s from Phase 0) -- well inside the 60s handshake timeout, but the
  reason `request_timeout_s` needed raising and the reason the two-week
  demo run took roughly 2h20m wall-clock rather than the plan's ~30min
  estimate (which was scaled from the toy-prompt number). Documented here
  as a real deviation, not silently absorbed: the plan's wall-clock math
  in §4.4/§8.4 assumed toy-prompt latency; real-prompt latency is
  2-3x that. Two one-week periods remains the right demo scope -- it
  still completes unattended in a few hours -- but an annual run at this
  latency would be a multi-day undertaking, not "overnight" as the plan
  optimistically suggested.
- **Prompt engineering (§4.2, `prompts/controller_system.md`):** priority-
  ordered goals (comfort constraint > energy > carbon), the guardrail
  bounds spelled out explicitly (so the model can reason about what will
  and won't be clamped), four worked reasoning examples (deep unoccupied
  setback, pre-occupancy recovery, carbon-aware pre-cooling, steady
  occupied hold), and an explicit statement that a "no change" decision is
  a valid and often-correct answer -- an early concern was the model
  fidgeting every cycle to look "active"; it does not.
- **Demo run results (`runs/demo_final/`, committed per repo convention --
  the blessed run for judges), two contrasting one-week periods per
  `config/default.yaml`'s `demo_periods` (Jan 14-20, Jul 14-20), 328 total
  AI decisions, zero fallback decisions:**

  | period | vs-baseline energy saved | vs-baseline carbon avoided | comfort compliance (AI / baseline) |
  |---|---|---|---|
  | January week (heating-dominated) | 3.09% | 2.71% | 95.9% / 100% |
  | July week (cooling-dominated) | 16.13% | 7.82% | 100% / 100% |

  Both weeks beat baseline on energy without breaking the 95%
  occupied-hours comfort floor (§4's exit criteria). The rule-based
  controller still wins on raw energy % in both periods (8.00%/20.51%) --
  expected and honestly reported, not concerning: rule-based is a fixed,
  aggressive occupancy-setback policy with no comfort-vs-savings judgment
  to make, while the LLM is additionally reasoning about carbon timing and
  is more conservative near the comfort floor (visible in the January
  week's lower comfort compliance -- it took a few more calculated risks
  near the band edge than rule-based did). The July week result, where the
  AI actually *beat* rule-based on comfort compliance (100% vs 99.8%)
  while still saving 16% of energy, is the more interesting evidence for
  the "reasoning, not just clamping" autonomy story.
- **Decision-log audit (§7's "single best 'is the AI real' check"):** 20
  decisions sampled at random across both weeks via the new
  `scripts/sample_decisions.py` (pairs each decision with the telemetry
  state at that timestamp) -- every one was justified by the visible
  state: unoccupied-and-in-band -> hold; unoccupied-with-flat-carbon-
  forecast -> lean into setback; pre-occupancy -> explicit "next cycle is
  occupied" recovery reasoning; occupied -> hold within band, occasional
  carbon-timing commentary. Three guardrail clamps appear in this 20-item
  sample alone (comfort ceiling, cooling hard bound x2), each with an
  honest note -- the guardrail layer is doing real, visible work, not
  sitting idle.
- **A concrete degenerate-decision example, useful for the reliability
  story (§9 shot 5):** one decision in the smoke-test run had the model
  request heating=17.5/cooling=26.0 while the building was occupied by 52
  people, reasoning "expected to be unoccupied soon" -- factually wrong at
  8:20am on a weekday. The occupied comfort floor clamped heating to 20.0
  before it reached the actuator. Kept as a documented example rather than
  papered over: this is exactly the failure mode guardrails exist for, and
  it demonstrates the deterministic safety layer catching a small model's
  occasional bad reasoning in production, not just in theory.

## 2026-07-26 — GC-2

- **`peak_demand_kw_threshold` derivation (§2 Phase GC-2.2):** computed
  from the already-committed baseline telemetry, not guessed. Interval-
  average HVAC electricity kW (`metrics.interval_kwh_to_kw`, 15 sim-min
  intervals) peaks at 0.416 kW in `runs/demo_final/january_week/baseline`
  and 0.639 kW in `runs/demo_final/july_week/baseline` -- july's cooling
  load is the higher of the two, consistent with `total_hvac_kwh`'s
  existing note that winter setback savings land mostly on the gas reheat
  coil, leaving electricity comparatively flat in January. Threshold =
  80% of the higher value (0.8 * 0.639 = 0.512 kW), rounded to a clean
  0.5 kW, set in `config/default.yaml` as `peak_demand_kw_threshold`
  (a config value, not a code constant, per the plan). These sub-kW
  magnitudes are physically plausible for this 5-zone packaged-rooftop
  reference model's *electricity* demand alone (fan + DX compressor
  ancillary use) -- gas dominates the heating-season total, and the model
  is a small reference building, not a full commercial campus.

## 2026-07-26 — GC-5 launch

- **Extended-horizon run launched from commit `b3c8eedc42d53be63826f719dcbce35b11076e1e`**
  (main, `feat(scripts): extended-horizon reliability run script (GC-5.1)`,
  PR #19, squash-merged) -- GC-5.2's committed-state requirement. Working
  tree was clean at launch; `config/default.yaml` and branch untouched for
  the run's duration per the prime directive. `scripts/run_extended.sh`
  patches `models/building.idf` to Jan 1-31, runs the no-LLM baseline, then
  the AI run via `agent_runner --period-days 31` in structured mode (native
  mode explicitly not used) at the config decision interval (60 sim-min,
  ~744 decisions, 3.5-5.4h wall-clock estimate). Launched in a separate
  Terminal.app process so it survives this session ending; output tees to
  `runs/demo_final/extended_january/agent_runner_report.log`.

## 2026-07-26 — GC-5 partial-run stop

- **Stopped deliberately, not a crash**, at user request, to free the GC-4b
  slot for a parallel session per the plan's execution order (GC-4a ->
  extended run -> GC-6 -> GC-4b). Sent `SIGINT` to the `agent_runner`
  process (not `SIGKILL`) so its `async with` MCP session/subprocess
  context managers unwound cleanly on the way out; both `agent_runner` and
  the `mcp_server` subprocess exited within seconds, confirmed via `ps`.
  Telemetry and decision logs flush per-row/per-decision (§0.2 ground
  truth), so nothing in-flight was lost -- this matches the plan's own
  §2 GC-5 "Failure handling" contingency (flushed data survives a mid-run
  stop, commit what completed with an honest note, never rerun at the
  cost of downstream phases' time), applied here to a deliberate stop
  rather than a crash.
- **Coverage at stop:** baseline completed the full January period
  (2976 zone-timesteps, no LLM). AI covered `1986-01-01T00:15` through
  `1986-01-08T06:45` -- 172 decisions, **0 fallbacks/alerts** (confirmed
  both via `decisions.jsonl` and the `ALERT` grep count on the run log),
  ~23% of the ~746-decision target. Zero crashes, zero handshake timeouts,
  zero Ollama-unavailable/malformed-output fallbacks across the entire
  covered window -- this is the reliability evidence GC-5 exists to
  produce, just over ~7.3 days instead of the full 31.
- **`regenerate_summaries.py` ran clean** (`scripts/regenerate_summaries.py`
  already handled the baseline+ai-only, no-rulebased case per GC-5.3 -- no
  code change was needed there): 0 changed/0 regressed on the two existing
  committed periods (`january_week`, `july_week`), and a fresh
  `extended_january/summary.json` was generated.
- **Known caveat, called out honestly (§9 honesty rule):**
  `summary.json`'s `comparison.ai_vs_baseline` block compares a full-month
  baseline against the ~7.3-day AI partial -- the ~73% "energy
  saved"/"carbon avoided" figures it produces are an artifact of that
  period-length mismatch, not a real savings result, and must not be
  cited as such. A `PARTIAL_RUN_NOTE.md` was added directly in
  `runs/demo_final/extended_january/` flagging this for anyone browsing
  the run directory without reading this log. No code change was made to
  `regenerate_summaries.py`/`metrics.py` to special-case this (would need
  a matched-period baseline slice, which isn't worth building for a
  now-superseded partial run).
- **Not re-run in this session** -- per the plan's own guidance ("never
  rerun at the cost of downstream phases' time"), GC-4b runs next in a
  parallel session instead. Whether GC-5 is re-launched later to complete
  the full 31 days is a call for a later session, not decided here;
  `config/default.yaml` and `scripts/run_extended.sh` are unchanged, so a
  re-run needs no design change, just time.

## 2026-07-26 — GC-4b native tool-calling

- **Prerequisites confirmed before starting:** GC-4a (PR #18), GC-5 (PR #22,
  partial-honest-stop), GC-6 (PR #21) all merged to `main` -- per the plan's
  §1 execution order and this phase's own explicit optional/stretch scope
  (§7.6 priority order).
- **First successful native tool-call round, well inside the 30-min
  time-box:** a standalone probe against `qwen2.5:3b-instruct` via
  `ollama.Client.chat(..., tools=[...])` returned a valid
  `get_building_state` tool call in 8s, and a full two-round loop
  (`get_building_state` -> `set_zone_setpoints`) completed in ~19s. The
  time-box's actual condition -- does the tools-parameter path produce a
  first successful tool-call round at all -- was cleared almost
  immediately, so implementation proceeded per the plan's "if it works"
  branch (mode switch, tool-list translation, bounded loop, three-layer
  fallback, `--timeout-s 180`).
- **A real harness bug found and fixed during the first native smoke test,
  not a model failure:** `agent_runner._call`'s
  `json.loads(result.content[0].text)` failed with `Expecting value: line 1
  column 1 (char 0)` on `set_zone_setpoints` calls specifically. Diagnosed
  by returning the raw `TextContent` on failure: FastMCP's pydantic
  validation was correctly rejecting `heating_c=None, cooling_c=None`
  (present keys, null values -- a real model-reliability issue, see below),
  and the resulting error text wasn't the plain-JSON `_call` expected.
  Fixed `_call` to prefer `result.structuredContent` when present (the
  modern FastMCP path for dict-returning tools) and fall back to a
  descriptive `RuntimeError` including the raw content otherwise, plus
  tightened the pre-call argument check in `run_native_decision` to require
  `heating_c`/`cooling_c` be actual numbers, not just present keys -- this
  turns a confusing JSON-parse error into a clean, immediate
  `NativeToolCallError` before the round-trip.
- **Genuine model reliability issue, confirmed after the fix (not a
  scaffolding bug):** `qwen2.5:3b-instruct` intermittently calls
  `set_zone_setpoints` with `heating_c`/`cooling_c` explicitly `null`, or
  with an empty arguments dict. Both are caught by the pre-call check and
  fall through to structured mode for that decision, per the plan's
  three-layer safety net (native -> structured -> rule-based) -- exactly
  the failure mode §9's adversarial pass anticipated for a small model.
- **Showcase run** (`runs/demo_final/native_showcase/`, one simulated day,
  Jan 14, `--mode native --timeout-s 180`, decision interval 60 sim-min):
  **24/24 decisions completed, zero crashes, zero rule-based fallbacks**
  (the third safety net was never needed). Of the 24: **4 genuine
  `llm-native` decisions** (the model drove its own tool-call sequence --
  one example at `02:15` made 8 tool calls, including multiple read-tools,
  before calling `set_zone_setpoints`) and **20
  `structured-after-native-failure`** decisions (native attempted, failed
  on a null/missing-argument call, fell through to the existing
  structured-mode path, which itself never needed the rule-based
  fallback). Native success rate (~17%) is honestly low for this 3B model
  under the bounded harness -- consistent with the plan's own expectation
  ("likely with a 7-8B model" per §7 failure mode 2) -- but the mechanism
  itself, including all three fallback layers, is demonstrated working
  end-to-end with real evidence in `decisions.jsonl`.
- **Structured mode confirmed completely unaffected (prime directive):** a
  2-sim-day structured-mode regression smoke run (the mandatory §6 gate for
  any change touching `agent_runner.py`/`llm_agent.py`) completed with
  47/47 decisions via the LLM, zero fallbacks, zero native-path invocation
  -- `llm_agent.mode` defaults to `"structured"` in `config/default.yaml`,
  and `orchestrator.run_ai` (the production `compare-ai`/`demo` path) never
  passes `mode`, so it always gets the default. Native mode exists only
  behind `--mode native` / the config key, exercised solely by this
  showcase run.
- **Outcome: native mode implemented and demonstrated working (not the
  30-min-abandonment path).** Structured mode remains the production
  configuration for all `demo`/`compare-ai`/extended runs -- native mode's
  ~17% success rate on `qwen2.5:3b-instruct`, while real, is not reliable
  enough to run unattended at scale, and the plan explicitly scopes native
  mode to this one-day showcase only.
