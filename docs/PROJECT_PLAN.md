# Honeywell Campus Connect — AI-Powered Autonomous Smart Building Optimization
## Complete Project Plan (v1.1, 26 July 2026 — revised for a 6–10 h implementation window)

> **v1.1 timeline revision:** roughly **6–10 hours remain for code implementation**, after which the video recording and official submission must happen. All per-phase budgets have been compressed accordingly (see §2 intro and the timing summary). Per-subtask minute estimates inside §2 are retained as *relative* effort weights from the original plan — treat them as proportions, not absolutes, and apply the mandatory descopes listed in the §2 intro. Anything marked **[CUT in v1.1]** is out of scope unless everything else is done early.

This document is written to be handed, section by section, to a coding agent with no other context. Every environment fact it needs is stated explicitly. **Ground truth about this machine (verified 26 Jul 2026):** macOS (Darwin 24.6.0), **Apple M2, arm64, 16 GB RAM**, EnergyPlus 26.1.0 installed at `/Applications/EnergyPlus-26-1-0`, verified working via a successful `1ZoneUncontrolled.idf` annual run. The install bundles `pyenergyplus` (the official Python API), `libenergyplusapi.26.1.0.dylib`, `libpython3.12.dylib`, example IDF files, and five TMY3 weather files. Nothing else has been built yet. Working directory for the project: `/Users/kanadb/Work/autonomous-building-optimisation-energyplus`.

---

## 1. Problem restatement and success criteria

### 1.1 Restatement

Build a closed-loop autonomous Building Management System (BMS) in which:

1. **EnergyPlus** simulates a building (the "physical plant") timestep by timestep — zone temperatures, HVAC energy, occupancy, weather.
2. At a regular decision interval, live simulation state is exposed through an **MCP server** as structured tools (read state, read history, write setpoints, read goals).
3. An **open-source LLM** acts as the autonomous controller: it is invoked as an MCP client, reads the state via tools, reasons about the three competing goals (minimize energy, maintain comfort, minimize carbon), and calls a write-tool to change operating parameters (thermostat setpoints, and optionally supply-air or ventilation parameters).
4. The write is **validated by deterministic guardrails**, then applied back into the running EnergyPlus simulation via the EMS actuator API, closing the loop.
5. A **dashboard** compares the AI-controlled run against a fixed-setpoint baseline run: energy saved, comfort maintained, carbon avoided, plus a visible trace of the AI's decisions and reasoning.

Deliverables: source code, building model(s), savings dashboard, architecture documentation, demo video.

Key framing decision: "real-time data" here means *live data from a running simulation*, not wall-clock real time. The loop is synchronous with simulation time — EnergyPlus pauses inside a callback while the agent decides. This is the standard interpretation for this challenge and dramatically de-risks the build (no real-time co-simulation clock synchronization needed). State this openly in the architecture doc; it is a strength (deterministic, reproducible), not a dodge.

### 1.2 Rubric, and what "good enough" means in a ~6–10 h build window

| Rubric axis | Minimum bar ("good enough") | Stretch |
|---|---|---|
| Reliability | AI-controlled annual-or-multi-week run completes end-to-end without crashing, twice in a row, with the LLM making 100+ decisions; guardrails catch every malformed LLM output; documented fallback controller takes over on LLM timeout | Graceful resume, multiple buildings/climates |
| Energy savings | 8–20% HVAC energy reduction vs a deliberately-reasonable (not straw-man) baseline, shown numerically | Time-of-day carbon-aware pre-cooling shown to shift load |
| Comfort | Occupied-hours temperature within comfort band ≥ 95% of hours (baseline typically ~99–100%); comfort violations charted honestly | PMV/PPD (Fanger) metric alongside temperature band |
| AI autonomy | LLM genuinely chooses setpoints via MCP tool calls with logged reasoning per decision; no human in the loop during the run | Agent also adjusts ventilation/night-purge; agent explains trade-offs when goals conflict |
| Code quality | Clean repo layout, typed config, docstrings, README that lets a stranger run it, a handful of meaningful tests, no secrets committed | CI check, lint config |
| Presentation | Architecture diagram, ≤5-min video with a live loop running and the dashboard, clear savings numbers | Live demo capability during judging |

**Honesty rule that wins rubric points:** the baseline must be defensible (e.g., constant 21 °C heat / 24 °C cool during occupied hours with modest night setback), and the comfort comparison must be shown even where the AI is slightly worse. Judges punish straw-man baselines.

**Open-source LLM requirement:** the problem statement says "open-source LLM." Use **Ollama** running a local model (recommended: `qwen2.5:7b-instruct` or `llama3.1:8b` — both handle tool/JSON calling acceptably on a Mac). Claude may be used to *develop* the code but must not be the controller in the demo. The controller interface must be model-agnostic so a larger model can be swapped in if the 7–8B model is too erratic.

---

## 2. Full phase breakdown

**Total coding budget: 6–10 h at keyboard**, followed by ~1.5–2 h for the demo video and official submission (outside this budget — protect it). Plan to the 8 h midpoint; the compressed per-phase allocations are:

| Phase | v1.1 budget | Notes |
|---|---|---|
| 0 Environment + repo | 0.75 h | Ollama model download runs in background |
| 1 API harness (read path) | 1.5 h | |
| 2 Actuation + baseline + guardrails | 2 h | Rule-based controller is minimal (it's mainly the LLM fallback) |
| 3 MCP server | 1.25 h | Stdio only; 4 tools max (drop `get_performance_so_far` if tight) |
| 4 LLM agent + closed loop | 2 h | Structured-output mode ONLY; native tool-calling is cut |
| 5 Dashboard | 1.25 h | Static (completed-run) mode only; live-refresh cut |
| 6 Docs (README + architecture.md) | 0.5 h | Write the mermaid diagram early, reuse in video |
| **Total** | **9.25 h** | At the 6 h floor, apply the §8.8 descope ladder from the start |

**Mandatory v1.1 descopes (decided now, not under pressure):** native MCP tool-calling by the LLM (structured-output mode is the design, not the fallback); GitHub Issues ceremony (§10.3 becomes a checklist file); PMV comfort metric (temperature band only); second climate; live-refresh dashboard; annual runs (2 contrasting weeks is the demo period); all pytest tests except `test_guardrails.py` and `test_decision_parsing.py`.

**Demo run strategy under this timeline:** kick off the final baseline + AI comparison runs the moment Phase 4 first works end-to-end, and build the dashboard/docs *while they run* — do not serialize "finish everything, then run."

Phases are strictly sequential except Phase 5 (dashboard), which can start any time after Phase 2's telemetry format is frozen. Subtask minute-estimates below are relative weights from the original 26 h plan — scale them to the budgets above.

### Phase 0 — Environment, repo, and toolchain bootstrap (0.75 h)

**Purpose:** a reproducible dev environment where Python can import the EnergyPlus API, Ollama serves a model, and the repo skeleton exists. **Exit criteria:** a Python one-liner successfully imports `pyenergyplus.api` and prints the EnergyPlus version; `ollama run <model>` returns a completion; repo pushed to GitHub with CI-less green start.

Subtasks, in order:

- **0.1 Create GitHub repo + local clone.** Inputs: none. Outputs: repo with README stub, `.gitignore`, LICENSE (MIT). Time: 15 min. Risk: none. (Full detail in §10.)
- **0.2 Python environment.** Decide interpreter: the bundled `libpython3.12.dylib` means the API binary targets **Python 3.12** — install/use Python 3.12 (via `uv` or pyenv), *not* 3.13. Create a venv; the EnergyPlus API is *not* pip-installable at matching version reliability, so the canonical approach is: add `/Applications/EnergyPlus-26-1-0` to `sys.path`/`PYTHONPATH` so `pyenergyplus` imports from the install itself (guarantees dylib/version match). Record this in a single config module and in the README. Inputs: EnergyPlus install path. Outputs: venv + a documented path-setup mechanism (env var `ENERGYPLUS_DIR` read by the config module). Time: 30 min. Risks: (a) Python minor-version mismatch → segfaults or import errors; (b) Apple Silicon vs Intel dylib — the installed E+ already runs natively per the verified test, so the API should too; (c) macOS Gatekeeper quarantining the dylib on first dlopen — fix is `xattr -d com.apple.quarantine` on the dylib if a "cannot be opened" dialog appears.
- **0.3 Verify pyenergyplus import + trivial API run.** Run the 1ZoneUncontrolled model *through the Python API* (not the CLI) into a scratch output dir. Inputs: 0.2, example IDF, EPW. Outputs: proof the API path works; note the exact run duration (~4 s annual — this matters for loop-cadence planning). Time: 20 min. Risk: working-directory pollution (E+ writes `eplusout.*` into cwd unless an output dir is passed — always pass one).
- **0.4 Install and verify Ollama + model.** Pull the chosen 7–8B model; verify a structured-JSON response to a toy prompt; measure single-completion latency on this Mac (expect 2–10 s). Outputs: measured latency number written into `docs/decisions.md` (drives decision-interval choice in Phase 4). Time: 25 min (model download can run in background during 0.2–0.3). Risk: model too slow/dumb → fallback list: `qwen2.5:7b` → `llama3.1:8b`. With 16 GB RAM (verified), a 7–8B model at Q4 quantization (~5 GB) is comfortable alongside EnergyPlus + Streamlit; a 14B model (~9 GB) is borderline — only try it with the dashboard and recorder closed, and never during the recorded demo.
- **0.5 Install remaining Python deps** (see §4) and freeze into `requirements.txt`/`pyproject.toml`. Time: 10 min.

**Validation before Phase 1:** the three smoke checks (API import+run, Ollama JSON reply, repo push) all pass, each captured as a tiny script under `scripts/` so they're re-runnable after any environment change.

### Phase 1 — Python API harness: read live state from a running simulation (1.5 h)

**Purpose:** wrap EnergyPlus in a Python class that runs a chosen IDF and surfaces per-timestep state via callbacks. This is the foundation everything sits on. **Exit criteria:** a run of the chosen HVAC building prints/logs zone temperature, outdoor temperature, and HVAC electricity for every zone timestep of a 1-week run period, with warmup and sizing periods correctly excluded.

Subtasks:

- **1.1 Choose and prepare the building model.** Copy `5ZoneAirCooled.idf` (or, if inspection shows it awkward, `RefBldgSmallOfficeNew2004_Chicago.idf`) from `ExampleFiles/` into `models/`. Requirements the model must satisfy — verify each by reading the IDF: (a) real HVAC with electricity consumption (not an uncontrolled zone); (b) thermostats driven by **named setpoint schedules** (these are what we actuate); (c) runs cleanly standalone with the Chicago EPW (Chicago gives strong seasonal contrast → bigger savings story than San Francisco). Trim `RunPeriod` to a configurable window (dev: 1 week; demo: 1 month or two contrasting months, e.g., January + July). If the file uses `HVACTemplate:*` objects it must be pre-expanded with `ExpandObjects` once and the expanded IDF committed — the API does not auto-expand. Inputs: ExampleFiles, InputOutputReference.pdf for object lookup. Outputs: `models/building.idf` + `models/README.md` describing zones, HVAC, schedules. Time: 60 min. Risk: highest-uncertainty subtask of the phase; if the chosen file fights back (severe errors, odd schedules), fall back to the other candidate rather than debugging >30 min.
- **1.2 Simulation wrapper class.** Runs E+ via the API in a **dedicated thread** (the API call blocks until simulation end; callbacks execute on that thread). Constructor takes IDF path, EPW path, output dir, and a callback hook. Time: 45 min. Risk: exceptions raised inside E+ callbacks can be swallowed or abort the run with no traceback — every callback body must be wrapped in a catch-all that logs the full traceback to a file before re-raising or setting a fatal flag.
- **1.3 Variable/meter handle acquisition.** At runtime, request handles for: per-zone air temperature; outdoor drybulb; per-zone people count (occupancy); HVAC electricity meter (e.g., `Electricity:HVAC`); optionally humidity. Handles are only valid once the API signals data is fully ready — must gate on that, and must hard-fail with a clear message listing the requested name if any handle comes back invalid (−1), because an invalid handle silently reads as garbage otherwise. Note: available variable names are discoverable in the `.rdd`/`.mdd` files from a prior run — do one plain run first and commit those files' relevant excerpts into `docs/`. Also: variables must be *requested* (via the API's request mechanism or `Output:Variable` objects in the IDF) before handles exist. Time: 60 min. Risk: name/key typos — the #1 silent failure in E+ API work; mitigate with the hard-fail rule.
- **1.4 Warmup/sizing filtering + timestep bookkeeping.** Ignore callbacks during warmup and design-day/sizing periods (API exposes flags for both); build a clean simulation-datetime from the API's month/day/hour/minute calls. Outputs: state records tagged with a proper timestamp. Time: 30 min. Risk: off-by-one on E+'s "hour 24 / minute 60" end-of-interval convention — normalize once, in one function, with a unit test.
- **1.5 Telemetry logger.** Every zone-timestep state record appended to CSV (and/or SQLite) in `runs/<run_id>/telemetry.csv`. This schema is the dashboard's input — freeze it here: timestamp, per-zone temps, outdoor temp, occupancy, HVAC power, cumulative HVAC energy, current setpoints, run_id, mode (baseline/ai). Time: 25 min.

**Validation before Phase 2:** plot (throwaway notebook or matplotlib PNG) one week of zone temperature vs outdoor temperature — daily swings and HVAC-driven regulation must be visibly physical. Cross-check total HVAC energy against `eplustbl.htm` from a plain CLI run of the same IDF — they must match within ~1%.

### Phase 2 — Actuation, baseline vs controlled, rule-based controller (2 h)

**Purpose:** prove the *write path* works and produce the baseline-vs-controlled comparison machinery with a deterministic controller before any LLM is involved. This is the project's insurance policy: if everything after this phase fails, this alone demonstrates a closed loop. **Exit criteria:** two runs (fixed baseline vs rule-based night-setback/occupancy controller) complete; the controlled run shows measurably lower energy; setpoint changes visibly take effect in the temperature traces.

Subtasks:

- **2.1 Actuator acquisition.** Get EMS actuator handles for the heating and cooling setpoint schedules (component type "Schedule:Compact"/"Schedule:Constant", control type "Schedule Value", key = schedule name from the IDF). Same hard-fail-on-invalid-handle rule. The list of *available* actuators for the model appears in the `.edd` file when the IDF contains an `Output:EnergyManagementSystem` object — add that object to the IDF and commit the relevant `.edd` excerpt to `docs/`. Time: 45 min. Risk: actuating a schedule that the thermostat doesn't actually reference (models sometimes have several similarly named schedules) — verify by actuating an absurd value (e.g., 15 °C cooling) for one day and confirming the zone temp responds.
- **2.2 Controller interface.** A single abstraction: given a state snapshot, return a decision (per-zone or global heating/cooling setpoints) or "no change." Baseline controller = never change (schedules as authored). Rule-based controller = occupancy-based setback (e.g., unoccupied: 15 °C heat / 30 °C cool; occupied: 21/24). Time: 45 min.
- **2.3 Decision-interval gating.** Controllers are consulted only every N simulation minutes (config; default 15 sim-minutes for rule-based, will be 60 for LLM), not every timestep. Time: 20 min.
- **2.4 Guardrail validator** (used by *all* controllers, including LLM later): setpoints clamped to hard bounds (heat 12–23 °C, cool 22–32 °C), heating < cooling − 1 °C deadband enforced, max change per decision (e.g., ≤ 3 °C step), occupied-hours comfort floor (during occupancy, heat ≥ 20 °C, cool ≤ 26 °C regardless of what the controller asked). Every rejection/clamp logged with reason. Time: 45 min. Risk: none technically; this is pure defense and directly feeds the "reliability" rubric axis.
- **2.5 Run orchestrator + metrics.** A single entry point that runs baseline then controlled with identical IDF/EPW/period, writes both telemetry sets, and computes the comparison: total/HVAC kWh, % saved, comfort-band compliance % during occupied hours, and carbon (kWh × emission factor; see §5 for the time-varying factor). Outputs: `runs/<run_id>/summary.json`. Time: 60 min.
- **2.6 Decision log.** Separate structured log (JSONL): timestamp, controller type, state snapshot summary, requested action, guardrail outcome, applied action, and (later) LLM reasoning text. This file is a first-class deliverable — it is the evidence of autonomy. Time: 25 min.

**Validation before Phase 3:** rule-based beats baseline on energy by a plausible margin (expect 5–15% for setback on this kind of model); comfort compliance during occupied hours stays ≥ 95%; the temperature trace visibly steps when setpoints change. If savings are ~0%, the baseline schedules probably already include setback — fix by *simplifying the baseline schedules in the IDF to constant occupied-hours setpoints* and rerunning (and document this as "baseline = conventional constant-setpoint operation," which is defensible).

### Phase 3 — MCP server (1.25 h)

**Purpose:** expose the running simulation as MCP tools so any MCP client (the LLM agent, or Claude Code itself during debugging) can read state and write setpoints. **Exit criteria:** with a simulation paused mid-timestep awaiting a decision, an MCP client can call every tool and get correct answers; a setpoint written via MCP takes effect in the simulation.

Architecture decision (make it and don't revisit): the MCP server and the simulation run **in the same Python process**. The simulation thread blocks on a decision-request queue at each decision interval; the MCP tool handlers read from a shared state object and post decisions to the queue. This avoids all cross-process serialization and timing problems. Use the official Python MCP SDK (`mcp` package, FastMCP-style server) over **stdio transport** for the agent, with an optional HTTP/SSE mode only if time allows.

Subtasks:

- **3.1 Shared state store** between sim thread and server: latest snapshot, rolling history (last 24 sim-hours), current setpoints, cumulative metrics, thread-safe. Time: 30 min.
- **3.2 Tool definitions.** Minimum tool set, each with a strict JSON schema and a docstring written *for the LLM* (these docstrings are prompt engineering): `get_building_state` (zones, temps, occupancy, outdoor conditions, current setpoints, current power, sim datetime), `get_recent_history` (hourly aggregates), `get_goals_and_constraints` (targets, comfort band, carbon intensity now and next 6 h forecast), `set_zone_setpoints` (per-zone or all-zone heating/cooling values; returns guardrail-adjusted applied values and any clamp reasons), `get_performance_so_far` (energy/comfort/carbon vs baseline expectation). Time: 75 min. Risk: over-scoping — resist adding more tools; five is enough.
- **3.3 Decision handshake.** The mechanism by which the sim thread says "decision point reached," waits (with timeout, default 60 s wall-clock), and proceeds with either the agent's validated decision or the rule-based fallback if the timeout fires. The timeout-fallback event is logged loudly. Time: 45 min. Risk: deadlock if the agent never calls the write-tool — the timeout is the defense; test it deliberately.
- **3.4 Manual MCP test.** Exercise the server from a scripted MCP client (and/or by registering it with Claude Code locally and poking it interactively). Time: 30 min.

**Validation before Phase 4:** a scripted client performs one full handshake cycle: state read → setpoint write → sim advances → next state reflects the change. Also verify the timeout path by simply not responding.

### Phase 4 — LLM agent and full closed loop (2 h; the heart)

**Purpose:** replace the rule-based controller with an open-source LLM making real decisions via MCP. **Exit criteria:** a multi-week AI-controlled run completes autonomously; decision log shows varied, state-dependent, reasoned decisions; results beat baseline on energy without gutting comfort.

Subtasks:

- **4.1 Agent runner.** A loop that, at each decision point: builds the conversation (system prompt + tool results), lets the model call MCP tools, and terminates the turn once `set_zone_setpoints` has been called (or explicit "no change"). v1.1: build **structured-output mode only** — the runner itself calls the MCP read-tools, packs the state into the prompt, requires a single JSON decision object back, and submits it to the MCP write-tool. The MCP layer is still genuinely in the loop, and this is dramatically more robust with 7–8B models. Native Ollama tool-calling driving MCP directly is **[CUT in v1.1]** — do not attempt it even if things go well; spend spare time on prompt quality instead. Time: 90 min. Risk: this is where small-model flakiness lives; the JSON-decision fallback plus guardrails plus timeout-fallback makes it survivable.
- **4.2 System prompt engineering.** The prompt must contain: role ("autonomous BMS controller"), the three goals with explicit priority ordering (comfort is a constraint, energy/carbon are objectives), the comfort band, the actuator semantics and bounds, the decision cadence, brief examples of good reasoning (pre-cooling before high-carbon evening peak; deep setback when unoccupied; recovery lead time before occupancy). Require a fixed output shape: short reasoning + decision. Iterate against logged transcripts. Time: 90 min, spread across testing. Risk: model ignores format → retry-once-then-fallback logic in the runner.
- **4.3 Reasoning capture.** Persist the model's full reasoning text per decision into the decision log; this feeds the dashboard's "AI decision feed" and the autonomy rubric axis. Time: 20 min.
- **4.4 Robustness hardening.** Malformed JSON → one repair-retry → fallback controller. Ollama connection refused → fallback + alert log. Repeated identical pathological decisions (e.g., always max setback) → detectable in review, addressed via prompt, not code. Wall-clock budget: with a 60-min sim decision interval, a 2-month run ≈ 1,460 decisions × ~5 s ≈ 2 h wall-clock — **therefore default demo run period = 2 contrasting weeks (Jan + Jul), ≈ 340 decisions ≈ 30 min wall-clock**, and make run period a single config value so longer runs can go overnight. Time: 60 min.
- **4.5 Full comparison runs.** Baseline vs rule-based vs AI, same period/weather, orchestrated by the Phase 2 runner; results into `runs/` with stable run_ids referenced by the dashboard. Time: 60 min of babysitting (overlap with Phase 5 work).
- **4.6 Tuning pass.** If AI underperforms rule-based: usually the prompt lacks the carbon/price signal exploitation or is too timid; give it the forecast tool output explicitly. If it violates comfort: guardrails already stop the worst; tighten occupied-hours floor. Time: 60 min.

**Validation before Phase 5 sign-off:** read 20 random decisions from the log — each must be justified by the state visible to the model at that moment (unoccupied → setback; pre-occupancy → recovery; high-carbon window → pre-cool earlier). This human read of the decision log is the single best "is the AI real" check.

### Phase 5 — Savings dashboard (1.25 h; parallelizable after Phase 2, build while final runs execute)

**Purpose:** the primary judge-facing artifact. **Exit criteria:** one screen tells the whole story in 10 seconds, with drill-down. Technology decision: **Streamlit** (fastest credible path; pure Python; auto-refresh for live mode; no node_modules). It reads `runs/*/telemetry.csv|summary.json` and the decision log — fully decoupled from the sim process, so a dashboard crash can never hurt a run.

Contents (minimum): headline stat tiles (kWh saved %, comfort compliance %, kg CO₂ avoided, # autonomous decisions); baseline-vs-AI cumulative energy chart; zone temperature vs comfort band with setpoint step overlay; carbon-intensity profile with AI load-shifting visible; live AI decision feed showing timestamped reasoning; run selector. Before writing any chart code, the coding agent must load the `dataviz` skill (if available in its environment). Subtasks: data-loading layer (45 min), stat tiles + energy chart (60 min), comfort/setpoint chart (45 min), decision feed (30 min), live-refresh mode reading a run in progress **[CUT in v1.1** — for the video's "live" feel, show the terminal decision-cycle output instead**]**, polish (30 min).

**Validation:** open dashboard on completed real runs; every number cross-checks against `summary.json`; nothing renders NaN when a run is mid-flight.

### Phase 6 — Documentation and architecture (0.5 h)

`docs/architecture.md` with a mermaid diagram (E+ ⇄ sim wrapper ⇄ shared state ⇄ MCP server ⇄ agent runner ⇄ Ollama; guardrails and fallback path drawn explicitly; dashboard as read-only observer), a sequence diagram of one decision cycle, the design-decision log (why in-process MCP, why sim-time not wall-clock, why structured-output mode, model choice, baseline definition), README with exact cold-start run instructions on macOS, and honest limitations section. Exit criterion: a stranger with EnergyPlus 26.1 + Ollama installed can reproduce the demo run from README alone.

### Phase 7 — Demo video + submission (~1.5–2 h, OUTSIDE the coding budget)

Shot list in §9. Record with QuickTime/OBS screen capture; script narration beforehand; keep ≤ 5 min. Reserve this time explicitly: **hard-stop all coding at least 2.5 h before the official deadline**, tag `v1.0-demo`, record, then submit with margin for upload problems.

### Phase timing summary and buffer (v1.1)

0: 0.75 h → 1: 1.5 h → 2: 2 h → 3: 1.25 h → 4: 2 h → 5: 1.25 h (partly parallel with final runs) → 6: 0.5 h ≈ 9.25 h at the top of the window; at the 6 h floor the §8.8 ladder applies from the start. Phase 7 (video, ~1.5 h) and submission sit **outside** the coding budget — schedule a hard stop for code at least 2.5 h before the deadline.

**Hard checkpoint rules:**
- **T+2.5 h:** Phases 0–1 done (state readable from a live run). If not, drop to the simplest IDF candidate immediately.
- **T+4.5 h:** Phase 2 done (actuation proven, baseline vs rule-based comparison exists). This is the insurance milestone — from here the project is demoable no matter what.
- **T+7 h:** Phase 4 first successful end-to-end AI run. If the LLM is still misbehaving here, freeze the prompt, accept guardrail-clamped behavior, start the final runs, and move to dashboard/docs.
- Activate descopes at the checkpoint, not "after one more fix."

---

## 3. Repository structure

```
autonomous-building-optimisation-energyplus/
├── README.md                     # cold-start setup + run instructions, headline results, screenshots
├── LICENSE                       # MIT
├── .gitignore                    # see §10.1
├── pyproject.toml                # project metadata + deps (or requirements.txt if faster)
├── .env.example                  # ENERGYPLUS_DIR, OLLAMA_MODEL, OLLAMA_HOST — no real .env committed
├── config/
│   └── default.yaml              # run period, decision interval, comfort band, guardrail bounds,
│                                 # emission-factor profile, model paths, run mode
├── models/
│   ├── building.idf              # the (possibly pre-expanded) building model, committed
│   ├── building_baseline_notes.md# what was changed from the stock example file and why
│   └── weather/
│       └── USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw   # copied from install for portability
├── src/
│   └── abms/                     # "autonomous BMS" package
│       ├── __init__.py
│       ├── config.py             # loads YAML + env; resolves ENERGYPLUS_DIR; sys.path setup for pyenergyplus
│       ├── simulation.py         # E+ wrapper: thread, callbacks, handles, warmup filtering
│       ├── datastore.py          # thread-safe shared state + history ring buffer
│       ├── telemetry.py          # CSV/SQLite logging, frozen schema
│       ├── guardrails.py         # deterministic validator/clamper
│       ├── controllers/
│       │   ├── base.py           # controller interface
│       │   ├── baseline.py       # no-op (schedules as authored)
│       │   ├── rulebased.py      # occupancy setback (also the LLM-failure fallback)
│       │   └── llm_agent.py      # agent runner: prompt build, Ollama calls, retry/fallback
│       ├── mcp_server.py         # tool definitions + decision handshake
│       ├── carbon.py             # time-varying grid-intensity profile + accounting
│       ├── metrics.py            # energy/comfort/carbon comparison, summary.json writer
│       └── orchestrator.py       # CLI entry: run baseline / rulebased / ai / compare
├── prompts/
│   └── controller_system.md      # the LLM system prompt, version-controlled like code
├── dashboard/
│   └── app.py                    # Streamlit app (reads runs/, never touches the sim)
├── scripts/
│   ├── smoke_energyplus_api.py   # Phase 0 checks, kept forever
│   ├── smoke_ollama.py
│   ├── discover_handles.py       # dumps rdd/mdd/edd-derived names for the model
│   └── run_demo.sh               # the exact command sequence used in the video
├── tests/
│   ├── test_guardrails.py        # the most important tests in the repo
│   ├── test_metrics.py
│   ├── test_timestamp_normalization.py
│   └── test_decision_parsing.py  # malformed-LLM-output handling
├── runs/                         # gitignored except curated demo runs
│   └── demo_final/               # the blessed run committed for judges (small CSVs + summary)
├── docs/
│   ├── architecture.md           # diagrams + design decisions
│   ├── decisions.md              # running log of choices with timestamps
│   ├── discovered_names.md       # variable/meter/actuator names from rdd/mdd/edd
│   └── demo_script.md            # video narration + shot list
└── .github/
    └── ISSUE_TEMPLATE/task.md    # see §10.3
```

Folder purposes: `src/abms` is everything that runs; `models` is the committed building deliverable; `prompts` treats the system prompt as reviewable source; `runs` separates artifacts from code (gitignored, with one curated exception); `scripts` holds re-runnable environment proofs; `dashboard` is deliberately isolated so it can only ever read files.

---

## 4. Dependencies and environment

| Dependency | Role | Version sensitivity / notes |
|---|---|---|
| EnergyPlus 26.1.0 (installed) | Simulation engine + Python API | API and `libenergyplusapi.26.1.0.dylib` are one unit; never mix API code from another version. `pyenergyplus` is imported from the install dir, **not** pip. |
| Python 3.12.x | Runtime | Must match the bundled `libpython3.12.dylib` era; do not use 3.13. |
| `mcp` (official Python SDK) | MCP server + client | Recent versions; stdio transport. |
| `ollama` (app) + `ollama` (pip) | Local open-source LLM serving + client | Model: `qwen2.5:7b-instruct` primary. Needs ~5–8 GB RAM free; fits the verified 16 GB M2. 14B models are borderline — see Phase 0.4. |
| `streamlit` + `pandas` + `plotly` (or altair) | Dashboard | None sensitive. |
| `pyyaml`, `pydantic` | Config + decision-schema validation | pydantic v2. |
| `pytest` | Tests | — |
| `matplotlib` | Throwaway validation plots in Phases 1–2 | — |
| QuickTime/OBS | Video | macOS built-in QuickTime is enough. |

macOS-specific: Gatekeeper quarantine on dylibs (fix noted in 0.2); E+ output-directory discipline (always pass an output dir via the API); Apple Silicon means everything above is arm64-native — no Rosetta anywhere. No Docker (adds nothing here, costs time). No Node/JS at all (Streamlit choice eliminates it).

---

## 5. Data requirements

**Building model:** one committed model is sufficient — a multi-zone office with real air-system HVAC and schedule-driven dual-setpoint thermostats (`5ZoneAirCooled.idf` first choice; DOE small-office reference second). Required edits: add EMS output object (for the `.edd` actuator listing), add needed `Output:Variable`/`Output:Meter` requests, possibly simplify thermostat schedules to a constant-occupied-setpoint baseline, set configurable RunPeriod. Realism budget: **do not** build a custom building, add detailed envelope realism, or model more than one HVAC topology — zero rubric value per hour. A second climate (Tampa or SF EPW swap) is a cheap stretch that demonstrates generality if time remains.

**Weather:** bundled Chicago TMY3 (strong heating *and* cooling seasons → richest AI behavior). Copy the EPW into the repo for self-containment.

**Occupancy:** whatever schedules the model ships with; expose people-count per zone to the agent. Don't build a stochastic occupancy model.

**Carbon intensity:** no live grid API (external dependency risk, and simulation-time ≠ wall-time anyway). Construct a **synthetic but realistic 24-h grid-intensity profile** (e.g., low midday solar-heavy ~0.25 kg CO₂/kWh, evening peak ~0.55, documented as "representative MISO/IL profile"). This is deliberate design, not a shortcut: it gives the LLM a real trade-off (pre-cool at clean/cheap hours) and makes the carbon axis demonstrable. Document the source/rationale in `docs/decisions.md`.

---

## 6. The closed control loop — one iteration, exactly

Setting: simulation mid-run, e.g., 14 July, 09:00 sim time, decision interval 60 sim-minutes.

1. **Callback fires.** EnergyPlus reaches the end of a zone timestep and invokes the registered end-of-zone-timestep callback on the simulation thread. Guard checks run first: not warmup, not a sizing/design-day period (else return immediately). *Silent-failure trap #1: forgetting these guards means the agent gets called during warmup with nonsense state — and warmup data pollutes telemetry.*
2. **State snapshot.** The wrapper reads every registered variable/meter handle and the current actuator values, normalizes the timestamp, appends to telemetry, updates the shared state store. *Trap #2: an invalid (−1) handle returns garbage, not an error — this is why Phase 1 hard-fails at handle acquisition. Trap #3: meter reads are cumulative in joules; energy-per-interval must be differenced, and unit conversion (J → kWh) done in exactly one place.*
3. **Decision-point check.** If less than the decision interval has elapsed since the last decision, the callback returns and the simulation proceeds — cheap timesteps vastly outnumber decision timesteps.
4. **Handshake.** At a decision point, the sim thread posts a decision request and blocks on a response queue with a 60 s wall-clock timeout. The simulation is now frozen mid-timestep; this is safe and by design. *Trap #4: any code path that can fail to post a response (agent exception, MCP transport death) without the timeout firing = permanent hang; the timeout must wrap everything.*
5. **Agent invocation.** The agent runner wakes, calls MCP read-tools (`get_building_state`, `get_goals_and_constraints`, optionally history/performance), assembles the prompt, and calls Ollama. *Trap #5: Ollama cold-start after model eviction can take 30+ s — keep-alive setting matters; measure in Phase 0. Trap #6: context growth across many decisions — each decision is a fresh conversation (stateless agent + a short rolling "recent decisions" summary injected as text), never an ever-growing chat.*
6. **Decision parsing.** The model's output must match the decision schema (pydantic-validated): per-zone or global heating/cooling setpoints + reasoning string. Malformed → one repair reprompt → fallback to rule-based decision, loudly logged. *Trap #7: a "successful" parse of semantically absurd values — that's the guardrails' job, next.*
7. **Guardrail validation.** Deterministic clamps and rejections (§2.4). The *applied* values may differ from *requested*; both are logged, and the write-tool's response tells the model what was actually applied (closing the agent's own feedback loop).
8. **Actuator write.** Validated setpoints written to the schedule-value actuator handles. *Trap #8: writing to a schedule the thermostat doesn't use — silently "works" while changing nothing; caught by the Phase 2.1 absurd-value test. Trap #9: an actuator, once written, holds its value until overwritten — "no change" decisions must either rewrite the current value or deliberately leave the override in place (choose: always write explicitly; never rely on E+ reverting).*
9. **Release.** The response queue is filled; the sim thread unblocks; EnergyPlus continues to the next timestep, where the new setpoints take physical effect. The decision log gains one JSONL record: state summary, reasoning, requested, applied, guardrail notes, latency, controller identity (LLM vs fallback).
10. **Observation of effect.** The next decision's state snapshot reflects the consequences — the loop is closed through the physics, not just through software.

End of run: E+ finishes, the wrapper joins the thread, metrics module writes `summary.json`, dashboard picks it up.

---

## 7. Testing and validation strategy

**Per-phase "actually right" checks** (beyond "didn't crash"):

- **Phase 1:** API-run HVAC energy matches CLI-run tabular report within 1%; temperature traces are physical (diurnal swing, regulation toward setpoints); timestamp unit test covers the hour-24 boundary and DST-free continuity.
- **Phase 2:** absurd-setpoint injection visibly moves zone temperature (proves actuation); rule-based savings in a plausible band (5–15%) — if >30%, suspect a broken baseline, not a great controller; comfort metric recomputed by hand for one day from raw CSV and compared to the metrics module.
- **Phase 3:** scripted full handshake round-trip; deliberate agent-silence test proves the timeout fallback; concurrent read during a decision doesn't corrupt state (basic thread-safety test).
- **Phase 4:** *decision-log audit* — sample ≥20 decisions and check each is justified by its visible state (this is the core "is the AI physically reasonable" check); *counterfactual probes* — feed the agent three hand-built states (deep night unoccupied, pre-occupancy winter morning, high-carbon summer evening) offline and check the decisions match engineering intuition (setback / recovery / pre-cool respectively); *degenerate-behavior scan* — histogram of all decided setpoints; a spike at one value means the model isn't reasoning, just pattern-matching; *comfort audit* — every occupied-hours band violation traced to cause (recovery lag vs bad decision).
- **Phase 5:** every dashboard number equals the corresponding `summary.json` value; charts render with a partial in-flight run.
- **Automated tests (pytest, run before every merge):** v1.1 keeps only the two highest-value files — guardrails (all clamp branches, deadband, occupied floor) and decision parsing (valid, malformed, missing fields, absurd values). Metrics-math and timestamp-normalization tests are **[CUT in v1.1]** (validate those manually via the Phase 1/2 cross-checks instead). Do **not** write tests that launch EnergyPlus — too slow and brittle for the window; the smoke scripts cover integration manually.
- **Reproducibility check (pre-demo):** rerun the blessed demo config from a fresh clone following only the README; identical energy numbers (the whole system is deterministic except the LLM — log seeds/temperature settings, and accept small decision variance while checking the *summary* stays in band).

---

## 8. Known failure modes and fallback plans (descope ladder)

Ordered by likelihood × damage:

1. **Small LLM can't do reliable MCP tool-calling.** Likely. Fallback already planned as primary: structured-output mode (runner calls tools, model returns one JSON decision). Rubric impact: none — MCP still carries all data, autonomy is intact.
2. **LLM decisions are erratic/harmful.** Guardrails cap damage; prompt iteration fixes most; if still bad, raise decision interval to 2 h (fewer, better-considered decisions) and/or swap to a 14B model overnight. Worst case: demo the rule-based controller as "safety fallback layer" *plus* the LLM run with guardrail interventions shown honestly — reliability rubric points survive.
3. **Handles/actuators for the chosen IDF won't cooperate.** Time-box 30 min, then swap to the alternate model file. Absolute worst case: switch the building to Ideal Loads with dual-setpoint thermostat (simplest actuatable configuration that still reports HVAC energy) — smaller realism, loop story untouched.
4. **Wall-clock blowup** (LLM latency × decisions). Already mitigated by 2-week demo period; further: 2 h decision interval, or 1-week period. The dashboard's story survives any period ≥ 1 week spanning one heating or cooling season.
5. **Threading deadlock/hang mid-demo.** The 60 s timeout + fallback controller means a run *cannot* hang if implemented as specified; additionally, never demo live-only — always have the pre-recorded video and the committed `runs/demo_final` for the dashboard.
6. **Ollama/machine resource exhaustion** (E+ + 8B model + Streamlit + screen recorder). Test the full stack concurrently once before recording; if tight, record dashboard and live-loop shots in separate takes.
7. **Environment breaks late** (brew upgrade, macOS dialog, etc.). Smoke scripts diagnose in seconds; nothing about the env is changed after T+24 h (freeze rule).
8. **Time runs out generally.** The v1.1 mandatory descopes (§2 intro) already cut: second climate, live-refresh dashboard, native tool-calling, PMV metric, most tests. If still short, the remaining ladder (cut from the bottom): dashboard polish → comfort/setpoint chart (keep tiles + energy chart) → run-length down to 1 week → rule-based comparison run (keep baseline vs AI only). Never cut: guardrails, decision log, baseline comparison, README, video.

---

## 9. Dashboard and demo requirements

**Dashboard minimum (judge-facing single screen):** four stat tiles — *Energy saved %, Comfort compliance % (vs baseline's %), CO₂ avoided kg, autonomous decisions made*; cumulative HVAC energy chart (baseline vs AI, gap shaded); one representative day's zone temperature with comfort band and setpoint steps overlaid; carbon-intensity curve with the AI's pre-cooling load shift visibly aligned to the clean-energy window; scrolling decision feed with timestamps and the model's own reasoning text; run/period selector.

**Demo video (≤ 5 min), shot-by-shot:**

1. (0:00–0:25) Title + one-breath problem statement over the architecture diagram. "A local open-source LLM autonomously operates a simulated office building through MCP."
2. (0:25–1:00) Architecture walkthrough on the diagram: EnergyPlus → MCP tools → LLM → guardrails → actuators → back into the physics. Emphasize *closed loop* and *deterministic safety layer* (reliability rubric).
3. (1:00–2:15) **Live terminal shot:** launch the AI run; show real decision cycles scrolling — state in, LLM reasoning text, guardrail verdict, applied setpoints. Pause on one good reasoning excerpt (autonomy rubric — this is the money shot).
4. (2:15–3:30) Dashboard tour: tiles first (savings %), then cumulative-energy gap, then the comfort chart ("we saved energy *without* leaving the band"), then the carbon load-shift chart ("it reasoned its way to pre-cooling when the grid is clean" — say "reasoned," not "learned").
5. (3:30–4:15) Reliability moment: show the guardrail log rejecting a bad LLM proposal and the timeout-fallback design; one sentence on tests. (Judges rarely see anyone demo their failure handling — cheap differentiation.)
6. (4:15–5:00) Repo flash (structure, README, docs), results recap card with the three headline numbers, limitations honesty (one sentence), close.

Record narration from `docs/demo_script.md`; capture at 1080p+; do the terminal shot with enlarged font.

---

## 10. Git and GitHub workflow — full detail

### 10.1 Initial setup

- Create the repo **on GitHub first** (private until submission rules say otherwise), with no auto-generated files, then clone — avoids the remote-mismatch fumble of `git init` + later remote add. Default branch `main`.
- First commit (repo skeleton only): README stub (title, one-paragraph goal, "Status: hackathon in progress"), LICENSE (MIT — signals code-quality maturity, zero cost), `.gitignore`, `.env.example`, empty folder structure with `.gitkeep` files.
- **`.gitignore` contents for this stack:** Python (`__pycache__/`, `*.pyc`, `.venv/`, `*.egg-info/`, `.pytest_cache/`, `.ruff_cache/`); environment/secrets (`.env`, `*.local.yaml`); EnergyPlus outputs — this is the big one — `runs/` (with a negation to force-include `runs/demo_final/`), and belt-and-braces patterns for stray outputs: `eplusout.*`, `eplustbl.*`, `eplusmtr.*`, `*.eso`, `*.mtr`, `*.audit`, `*.bnd`, `*.eio`, `*.end`, `*.mdd`, `*.rdd`, `*.edd`, `*.dxf`, `*.shd`, `*.rvaudit`, `*.mtd`, `sqlite.err`; macOS (`.DS_Store`); IDE (`.idea/`, `.vscode/` except shared settings if any); Streamlit (`.streamlit/secrets.toml`); no Node section needed (no JS in the stack); large model artifacts never enter the repo (Ollama stores models outside it anyway). EPW weather file (~1.6 MB) **is** committed deliberately.

### 10.2 Branching strategy — recommendation: trunk-based, no develop branch

Justification: solo-or-tiny team, 36 hours, phases strictly sequential — a `develop` branch adds merge ceremony with zero isolation benefit. Rules: `main` is always runnable (smoke scripts pass); all work on short-lived branches named `feat/<phase>-<slug>` (e.g., `feat/p2-guardrails`), `fix/<slug>`, `docs/<slug>`; branches live hours, not days; merge to `main` only when the subtask's validation check passes. A phase's exit criteria being met is marked by a tag (below), not a branch.

### 10.3 Issue tracking — v1.1: lightweight checklist instead of full Issues

With 6–10 h, full GitHub-Issue ceremony (one issue per subtask, labels, milestones, templates) costs more than it returns. **v1.1 approach:** a single `TODO.md` checklist in the repo root mirroring the §2 subtask list, checked off per commit; plus at most **one GitHub Issue per phase** (7 issues total, created in one 5-minute `gh` CLI batch) so commits still have `(#N)` references and the repo still shows process to judges. Original full scheme (kept for reference if this becomes a multi-day team effort): one issue per atomic subtask with labels `phase-N`, `blocker`, `stretch`, `rubric:*`, template fields *Goal / Inputs / Outputs / Depends on / Validation check / Time box / Rubric axis*, milestones = phases.

### 10.4 The per-task loop

1. Pick the next issue in build order (blockers first).
2. Branch from up-to-date `main`: `feat/p3-mcp-tools` (reference the issue in the branch description or name suffix `-#23` if desired).
3. Commit in **Conventional Commits** format, small and frequent: `feat(mcp): add get_building_state tool (#23)`, `fix(sim): guard warmup timesteps (#14)`, `test(guardrails): deadband clamp cases (#19)`, `docs: architecture sequence diagram (#31)`. Reference the issue number in every commit; use `Closes #23` in the final commit or PR body for auto-close.
4. Push at every commit (the laptop is a single point of failure; GitHub is the backup).
5. Open a PR even solo — it's a 90-second self-review checkpoint: read the diff top to bottom, run `pytest` + the relevant smoke script, confirm the issue's Validation field is satisfied. Skip PR ceremony (templates, reviewers) — the diff read is the point.
6. **Merge strategy: squash-merge.** One issue → one clean commit on `main`; keeps `main` history a readable phase narrative and makes `git revert` of a whole subtask trivial. Delete the branch on merge (GitHub auto-delete setting on).
7. Issue auto-closes; move on.

Time-pressure concession: for genuinely trivial changes (typo, config tweak) committing directly to `main` is acceptable — declare this rule up front so it's a policy, not a lapse.

### 10.5 When something breaks mid-hackathon

- **Uncommitted WIP blocking an urgent fix:** `git stash` (with a message), fix on a fresh branch, `git stash pop` after. Never stash for hours — stashes get forgotten; prefer a WIP commit on the branch.
- **A merged change broke `main`:** `git revert <squash-commit>` — safe, history-preserving, instant return to known-good; then fix forward on a branch. This is where squash-merging pays off (one revert = one subtask).
- **`git reset --hard`** only for *local, unpushed* mess; never rewrite pushed history during the hackathon — with possible teammates and time pressure, force-pushes are how repos die at 3 a.m.
- **Hotfix branch (`fix/…` straight off `main`) is warranted when:** `main` is broken *and* someone/something else (teammate, the dashboard, a running long simulation) depends on `main` right now. Otherwise just fix forward on the current feature branch.
- **Long simulation runs vs git:** never switch branches in a working tree while a run is writing into `runs/` — runs write to gitignored paths so it's *safe*, but code hot-reload confusion isn't; start long runs from a tagged commit and note the tag in the run's `summary.json`.

### 10.6 Release tagging

Annotated tags at every phase exit: `v0.1-sim-harness`, `v0.2-closed-loop-rulebased`, `v0.3-mcp`, `v0.4-ai-loop`, `v0.5-dashboard`. Then the critical one: **`v1.0-demo` tagged on the exact commit that produced `runs/demo_final` and the video**, at least 3 h before the deadline. After tagging, `main` may still take polish, but the demo is *always* runnable via `git checkout v1.0-demo`. The README states this tag explicitly for judges.

### 10.7 If it becomes a team

- Assignment: issues assigned at pickup, never in advance (people's speed varies wildly under pressure); one issue per person at a time; the `blocker` label queue is sacred.
- **Conflict avoidance given sequential Phases 1–3:** don't parallelize *within* the critical path — parallelize *across* concern boundaries that share only frozen interfaces. Person A owns the critical path (Phases 1→2→3→4: `simulation.py`, `mcp_server.py`, `controllers/`). Person B owns everything downstream of the **telemetry schema** (frozen at 1.5): dashboard, metrics, carbon profile — buildable against hand-written fixture CSVs before real data exists. Person C (if any) owns models/IDF work, prompts, docs, issue hygiene, and the demo script. The only shared files are `config.py`/`default.yaml` — changes to those announced in chat before pushing.
- Merge discipline: rebase-or-merge from `main` into your branch before opening a PR; PRs reviewed by the other person when touching shared files, self-reviewed otherwise; short sync every ~3 h against the milestone board.

---

## 11. Final adversarial pass — where this plan would actually fail, and revisions made

Reviewed against realistic hackathon failure patterns; the fixes are already incorporated above:

1. **Biggest schedule risk is Phase 1.1/2.1 (IDF + actuator archaeology), not the AI.** Everyone budgets fear for the LLM; the real time sink is discovering that the example file's thermostat references a schedule you didn't actuate. *Revision applied:* the absurd-value actuation test is mandatory and early (2.1), both candidate IDFs are named, and a 30-minute time-box with a named fallback (Ideal Loads) is codified in §8.3. Also, `discover_handles.py` and committed `.edd`/`.rdd` excerpts exist precisely so the coding agent never guesses names.
2. **Assumption that might not hold: the 7–8B model produces usable decisions at all.** If it doesn't, the original "agent calls MCP tools natively" design would eat the whole night. *Revision applied:* structured-output mode was promoted from fallback to the **default demo configuration**, with native tool-calling as stretch. This is the single most important de-risking decision in the plan.
3. **Wall-clock math was initially optimistic.** An annual AI run at 1-h decisions ≈ 8,760 LLM calls — hours of wall-clock and thousands of chances to flake. *Revision applied:* demo period cut to two contrasting weeks (~340 decisions), period made a config value, and the overnight slot reserved for the one long run if things go well.
4. **The baseline could accidentally be too good** (stock example schedules often already have setback), yielding embarrassing ~0% savings late in the build. *Revision applied:* Phase 2 validation explicitly checks for this and prescribes the fix (constant-setpoint baseline schedules, documented as conventional operation) *before* the LLM phase, when it's cheap.
5. **Threading + callbacks is a silent-failure minefield** (swallowed exceptions, hangs). *Revision applied:* catch-all logging in every callback (1.2), the timeout-wrapped handshake as the only blocking point (3.3), and a deliberate hang-test (agent stays silent) as a phase-exit check.
6. **Buffer honesty (v1.1):** 9.25 h of estimates against a 6–10 h window means the plan only closes at the top of the window, and estimates under pressure run 1.3×. *Revision applied:* mandatory descopes decided up front (§2 intro), three hard checkpoints at T+2.5/4.5/7 h, dashboard/docs built while the final runs execute, and a protected 2.5 h pre-deadline hard stop for video + submission. The plan's real safety isn't buffer, it's that **Phase 2 alone (T+4.5 h) is a demoable closed-loop system**, and every later phase only adds rubric points on top of a working core.
7. **What could not be verified in advance — Phase 0 must confirm:** ~~exact Mac RAM and Apple Silicon vs Intel~~ (verified 26 Jul 2026: **Apple M2, arm64, 16 GB**), whether `pyenergyplus` import-from-install works cleanly with a system Python 3.12 (the 0.3 smoke test settles this in minutes, with the bundled `libpython3.12` as evidence for 3.12 and the E+ install's own Python as an emergency interpreter), and current Ollama tool-calling quality for the chosen model (0.4 measures it). All four are checked inside the first 90 minutes, before anything is built on top of them.

**Handover protocol for the coding agent:** implement one phase at a time; along with each phase's section, always provide §3 (repo structure), §4 (dependencies), and §6 (loop mechanics) as standing context. Do not authorize the next phase until the current phase's named exit-criteria evidence exists.
