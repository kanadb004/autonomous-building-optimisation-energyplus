# Honeywell Campus Connect — Gap-Closure Plan (rubric alignment pass)
## Complete implementation plan v1.0, 26 July 2026 — companion to `docs/PROJECT_PLAN.md`

This document is written to be handed, phase by phase, to a coding agent (Claude Sonnet in Claude Code) that has **no other context**. It specifies every change needed to close the gaps between what is already built (Phases 0–4 of `docs/PROJECT_PLAN.md`, complete and working) and the official evaluation rubric. Read §0 (current-state ground truth) before implementing anything — it is verified against the actual code as of 26 July 2026, and every phase below references it.

**Prime directive: do not break the working system.** Phases 0–4 are done, validated, and produce correct runs. Every change in this plan is additive. If a change would require restructuring existing modules, stop and flag it instead.

---

## 0. Current-state ground truth (verified against the code, 26 July 2026)

### 0.1 Environment

- macOS Darwin 24.6.0, **Apple M2, arm64, 16 GB RAM** (verified).
- EnergyPlus 26.1.0 at `/Applications/EnergyPlus-26-1-0`; `pyenergyplus` is imported from that install dir (NOT pip) via `abms.config.ensure_pyenergyplus_on_path()`. Python 3.12 venv. Run everything with `PYTHONPATH=src` from the repo root `/Users/kanadb/Work/autonomous-building-optimisation-energyplus`.
- Ollama serves the open-source controller model (model name comes from `config/default.yaml` `llm_agent.model`, overridable via `OLLAMA_MODEL`). **Measured completion latency on this machine: 17–26 s per decision.** This number drives all wall-clock math below and must be quoted in the architecture doc.

### 0.2 What exists and works (do not rebuild)

Package `src/abms/`:

- `config.py` — YAML + env loading; `load()`, `llm_agent_config()`, `ensure_pyenergyplus_on_path()`. Config file `config/default.yaml` has (at least) `decision_interval_minutes` (with a `llm` key) and an `llm_agent` section (`model`, `host`, `history_hours`, …).
- `simulation.py` — `SimulationRunner`: threaded E+ wrapper, callbacks, variable/actuator handles, warmup/sizing filtering, per-timestep `on_state` and per-decision `on_decision` hooks, `mute_console`.
- `telemetry.py` — frozen CSV schema. `ZONE_NAMES = ["SPACE1-1", "SPACE2-1", "SPACE3-1", "SPACE4-1", "SPACE5-1"]`. `FIELDNAMES` = `timestamp, run_id, mode`, then `zone_temp_c_<Z>` ×5, `zone_occupant_count_<Z>` ×5, then `outdoor_temp_c, heating_setpoint_c, cooling_setpoint_c, hvac_electricity_interval_kwh, hvac_electricity_cumulative_kwh, hvac_gas_interval_kwh, hvac_gas_cumulative_kwh`. `TelemetryLogger` flushes every row.
- `metrics.py` — `load_telemetry`, `total_electricity_kwh`, `total_gas_kwh`, `total_hvac_kwh` (electricity+gas; setback savings land mostly on gas in winter), `total_carbon_kg` (hour-indexed electricity intensity via `abms.carbon` + flat gas factor), `comfort_compliance_pct` (per-zone occupied timesteps within `[OCCUPIED_HEAT_FLOOR_C, OCCUPIED_COOL_CEILING_C]`), `summarize_run(run_dir)`, `compare_runs`, `compare_three(baseline_dir, rulebased_dir, ai_dir)`, `write_summary`.
- `guardrails.py` — exported constants used elsewhere: `HEATING_MIN_C/HEATING_MAX_C/COOLING_MIN_C/COOLING_MAX_C/MIN_DEADBAND_C/MAX_STEP_C/OCCUPIED_HEAT_FLOOR_C/OCCUPIED_COOL_CEILING_C`, plus the clamp/validate function used by the sim thread.
- `mcp_server.py` — in-process FastMCP server (stdio) + `SimulationRunner` in one process; `build_server(datastore, handshake, decision_interval_minutes)` exposes exactly five tools: `get_building_state`, `get_recent_history`, `get_goals_and_constraints`, `set_zone_setpoints(heating_c, cooling_c, reasoning)`, `get_performance_so_far`. Tool docstrings are prompt engineering — written for the LLM. `main()` takes `--idf --epw --output-dir --run-id --decision-interval-minutes --timeout-s`.
- `decision_handshake.py` — `DecisionHandshake` with `DEFAULT_TIMEOUT_S` (60 s) and `APPLIED_RESULT_TIMEOUT_S`; sim thread blocks at decision points; timeout → rule-based fallback via `MCPBridgeController`.
- `agent_runner.py` — the MCP *client* / AI loop (structured-output mode): spawns `abms.mcp_server` as a stdio subprocess, polls `get_building_state` until `awaiting_decision`, calls `get_goals_and_constraints` + `get_recent_history`, calls `llm_agent.propose(state, goals, history)` → decision with `.heating_c/.cooling_c/.reasoning`, submits via `set_zone_setpoints`, logs `requested/applied/guardrail_notes`. Catches `OllamaUnavailableError` and `DecisionParseError` → runner-side `RuleBasedController` fallback with an ALERT log line. CLI: `python -m abms.agent_runner --idf … --epw … --run-id … --output-dir … --period-days N`.
- `controllers/` — `base.py`, `baseline.py`, `rulebased.py` (`RuleBasedController.decide(state) -> (heating_c, cooling_c)`), `llm_agent.py` (`LLMAgent`, `propose`, Ollama HTTP client, retry-once-on-malformed), `mcp_bridge.py`.
- `decision_parsing.py` — pydantic-validated decision schema + `DecisionParseError`.
- `carbon.py` — `intensity_for_hour(hour)` synthetic 24-h grid profile, `kwh_to_kg_co2`, `gas_kwh_to_kg_co2`.
- `orchestrator.py` — CLI entry running baseline / rulebased / ai / compare; uses `idf_utils.with_run_period` to write a RunPeriod-patched IDF into the run directory.
- `idf_utils.py` — `with_run_period(idf_path, begin_month, begin_day, end_month, end_day, output_path)`: text-patches the `RunPeriod` object, fails loudly if not found.

Other assets: `models/building.idf` (5ZoneAirCooled-derived, Chicago EPW at `models/weather/USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw`), `prompts/controller_system.md`, `scripts/` smoke tests + `sample_decisions.py`, `tests/test_guardrails.py` + `tests/test_decision_parsing.py` (passing), `docs/decisions.md`.

Completed demo runs on disk (telemetry + `decisions.jsonl` + `summary.json` + the runtime-patched `building.idf` per period):
- `runs/demo_final/january_week/{baseline,rulebased,ai,building.idf,summary.json}`
- `runs/demo_final/july_week/{…same…}`

`dashboard/app.py` is a **one-line stub**. `docs/architecture.md` is a **stub**.

### 0.3 The rubric being closed against

Weighted criteria: **System Integration 30%** (closed loop + robustness over an extended simulation horizon), **Thermal Comfort & Constraints 20%** (explicitly names **PMV**; also mentions indoor air quality and peak-demand thresholds as signals the LLM should respect), **Energy/Carbon results**, **Agentic Autonomy 15%** (effective/creative leverage of MCP protocols and **self-correction loops**), plus deliverables: baseline **and runtime-modified IDF files** committed, **quantitative savings dashboard**, **System Architecture Document** (must cover tool-calling architecture, prompt engineering strategy, prompt latency management, handling of lengthy simulation logs), **demo video ≤ 3 min** (note: shorter than the old plan's 5 min), presentation slides on the official template.

---

## 1. Gap inventory → phase map

| # | Gap | Rubric axis (weight) | Phase | Code? |
|---|---|---|---|---|
| G1 | Runtime-modified IDFs not committed as artifacts | Deliverables | GC-1 | tiny |
| G2 | No peak-demand threshold signal | Comfort & Constraints (20%) | GC-2 | yes |
| G3 | No PMV comfort index | Comfort & Constraints (20%) | GC-3 | yes |
| G4 | No indoor air quality modeling | Comfort & Constraints (20%) | GC-7 (conditional) | yes + resim |
| G5 | No native LLM tool-calling / thin self-correction story | Agentic Autonomy (15%) | GC-4 | yes |
| G6 | No extended-horizon reliability proof | System Integration (30%) | GC-5 | tiny + unattended run |
| G7 | Dashboard entirely missing | Deliverables + presentation | GC-6 | yes |
| G8 | Architecture doc a stub; video not re-scoped to ≤3 min; slides | Deliverables | GC-8 | docs only |

**Execution order (dependencies dictate it):** GC-1 → GC-2 → GC-3 → *regenerate summaries* → GC-4a (self-correction) → **launch GC-5 extended run (unattended)** → GC-6 dashboard → GC-4b (native tool-calling, time-boxed) → GC-7 (only if time) → GC-8 docs. Rationale: GC-2/GC-3 add fields to `summary.json` that GC-6 renders, so metrics must land before the dashboard; the extended run takes ~4–5 h of *wall-clock but zero attention*, so it must start as early as its prerequisites (GC-4a, ideally) exist.

---

## 2. Phase breakdown

### Phase GC-1 — Commit the runtime-modified IDF artifacts (15 min)

**Purpose:** satisfy the deliverable "baseline + runtime-modified .idf files saved," which is currently 90% done — `orchestrator.py` already writes the `with_run_period`-patched IDF into each period directory (`runs/demo_final/january_week/building.idf` exists on disk). **Exit criteria:** `git ls-files` shows the demo-run artifacts (patched IDFs, telemetry CSVs, `summary.json`, `decisions.jsonl`) tracked; a fresh clone contains them.

Subtasks:

- **GC-1.1 Fix the `.gitignore` negation.** Inspect the current `.gitignore`. Git cannot re-include a file if a parent directory is excluded, so a bare `!runs/demo_final/` under `runs/` does not recurse. Required pattern set, in order: ignore `runs/*`, un-ignore `runs/demo_final/`, un-ignore `runs/demo_final/**`. Keep bulky raw E+ outputs excluded *by extension* even inside `demo_final` (`*.eso`, `*.mtr`, `*.audit`, `*.eio`, `*.bnd`, `*.shd`, `*.mtd`, `*.rdd`, `*.mdd`, `*.edd`, `*.dxf`, `*.rvaudit`, `eplusout.*`, `eplustbl.*`) — the committed artifacts are the CSVs, JSONs, JSONL, and IDFs only. Validate with `git check-ignore -v` on one path of each kind (a telemetry.csv that must be tracked, an eplusout.eso that must not). Time: 10 min. Risk: the negation ordering — test, don't assume.
- **GC-1.2 Record model provenance per run.** In `orchestrator.py`, where the patched IDF is written, also record in the run's `summary.json` (or a small `manifest.json` next to it) the source model path (`models/building.idf`) and its current git hash (`git rev-parse` at run time is NOT available inside the run — instead compute a SHA-256 of the source IDF file contents in Python and store it). This makes each committed run dir self-describing: original model reference + runtime-modified variant side by side. Time: 5 min.
- **GC-1.3 Commit** `runs/demo_final/january_week/` and `runs/demo_final/july_week/` per §8's workflow.

**Validation:** clone the repo to a temp dir (or `git stash` + `git checkout` in a scratch worktree) and confirm the artifacts are present and the dashboard-relevant files are all there.

### Phase GC-2 — Peak-demand threshold signal (45 min, no simulation changes)

**Purpose:** give the LLM an explicit peak-demand target to reason about and report peak-demand results — the rubric names peak-demand thresholds as a constraint signal. Everything needed already exists in telemetry: interval electricity kWh over a known interval length ⇒ average kW for that interval.

Subtasks, in order:

- **GC-2.1 Interval-length derivation.** Add a helper in `metrics.py` that derives the zone-timestep length in minutes from the first two telemetry timestamps (timestamps are ISO strings; the schema is frozen — do not add a column). All kW math uses this. Handle the degenerate 0/1-row case by returning a sensible default and flagging it.
- **GC-2.2 Choose the threshold empirically.** One-off: compute the baseline run's peak interval-average electricity kW from `runs/demo_final/january_week/baseline/telemetry.csv` and `july_week`'s; set `peak_demand_kw_threshold` in `config/default.yaml` to ~80% of the higher of the two, rounded to a clean number. Record the derivation in `docs/decisions.md`. The threshold is a *config value*, not a constant in code.
- **GC-2.3 Metrics.** In `metrics.py`: extend `summarize_run` with `peak_demand_kw` (max interval-average electricity kW), `peak_demand_at` (timestamp of that max), and `pct_intervals_above_threshold` (threshold read from config; pass it in as a parameter with the config value as the caller-supplied default — `metrics.py` should not import config directly if it currently doesn't). Extend `_comparison` with `peak_demand_reduction_kw` and `peak_demand_reduction_pct`.
- **GC-2.4 MCP exposure.** In `mcp_server.py`: `get_building_state` additionally reports `current_demand_kw` (latest interval electricity kWh × 60 / interval-minutes; the server knows the decision interval and can carry the timestep length from the datastore — compute it the same single way as GC-2.1, do not duplicate the formula); `get_goals_and_constraints` adds a `peak_demand` entry under goals: the threshold in kW and one sentence of guidance ("keep instantaneous HVAC demand below this; pre-conditioning earlier is preferable to peak-hour catch-up"). Remember tool docstrings are prompt engineering — mention the new field there too.
- **GC-2.5 Prompt.** Add one short paragraph to `prompts/controller_system.md` naming the peak-demand goal and the trade-off (pre-cool/pre-heat during low-demand, low-carbon hours instead of spiking at occupancy start).

**Validation:** run `metrics.compare_three` over the existing january_week dirs (no resim) and eyeball that `peak_demand_kw` values are physically plausible (a 5-zone office packaged-HVAC system: order of single-digit-to-tens of kW, and the baseline morning-recovery peak should exceed the AI run's if pre-conditioning happened). Unit-test the kW conversion with a synthetic two-row fixture.

### Phase GC-3 — PMV thermal comfort index (1–1.5 h, no simulation changes)

**Purpose:** the rubric explicitly names PMV; the current metric is temperature-band-only. **Design decision (made — do not revisit):** compute PMV post-hoc in Python from the already-recorded telemetry, NOT via EnergyPlus's native Fanger reporting. The E+ route needs clothing/activity/air-velocity schedules added to every People object plus a resimulation of every run — high risk, zero additional rubric value. The Python route retrofits PMV onto the *existing* january/july telemetry with no resim.

Subtasks:

- **GC-3.1 New module `src/abms/comfort.py`.** A self-contained Fanger PMV implementation per ISO 7730 / ASHRAE 55 (the standard iterative clothing-surface-temperature solution). Inputs: air temp °C, mean radiant temp °C, relative humidity %, air velocity m/s, metabolic rate met, clothing clo. Fixed assumptions, stated in the module docstring AND in the architecture doc: MRT = air temperature (no surface-temp data in telemetry), RH = 50% (humidity not tracked), air velocity = 0.1 m/s (still indoor air), metabolic rate = 1.1 met (office work), clothing = 1.0 clo for heating months (Oct–Apr) and 0.5 clo for cooling months (May–Sep), selected by the timestamp's month. Expose one high-level function that takes (air_temp_c, month) and returns PMV using those assumptions, plus the low-level six-parameter function for testing. **Do not add a pip dependency** (`pythermalcomfort` would work, but the network is unreliable in this environment and the equation set is ~40 lines; self-contained wins).
- **GC-3.2 Metrics.** In `metrics.py`: over occupied zone-timesteps only (same occupancy condition `comfort_compliance_pct` already uses), compute and add to `summarize_run`: `pmv_mean`, `pmv_mean_abs`, and `pmv_within_pct` (% of occupied zone-timesteps with |PMV| ≤ 0.5 — the ASHRAE 55 comfort criterion). Add `pmv_within_delta_pct` to `_comparison`. The temperature-band metric stays; PMV is additive.
- **GC-3.3 MCP exposure.** `get_building_state` adds per-zone `pmv` (computed on the fly from the zone temp + sim month via `comfort.py`); `get_goals_and_constraints` adds the |PMV| ≤ 0.5 target sentence under the comfort constraint. One line in `prompts/controller_system.md`.
- **GC-3.4 Tests — `tests/test_comfort.py`.** PMV math fails silently when wrong, so anchor it: (a) verification cases — ASHRAE 55: air=MRT=19.6 °C, RH 86%, v 0.1 m/s, 1.1 met, 1.0 clo → PMV ≈ −0.5, and ISO 7730:2005 Annex: air=MRT=27.0 °C, RH 60%, v 0.1 m/s, 1.2 met, 0.5 clo → PMV ≈ +0.77, both within ±0.15 (if the implementation misses these tolerances, debug the radiative/convective terms before loosening the test). **Note (post-implementation correction):** the warm case originally specified here as 25.7 °C/RH 67%/1.1 met/0.5 clo → PMV ≈ +0.5 was a bad transcription — it failed by 0.27 under debugging while the cold anchor and independent sanity checks (neutral-point crossing near 26 °C, monotonicity) all held, isolating the error to the anchor, not the code. Replaced with the ISO 7730 Annex row above, confirmed against the standard's own verification data. (b) monotonicity — PMV strictly increases with air temperature, all else fixed; (c) neutrality sanity — with the module's own fixed assumptions there exists a temperature in 20–26 °C where |PMV| < 0.3.
- **GC-3.5 Regenerate summaries (also picks up GC-2).** Add `scripts/regenerate_summaries.py`: for each period dir under `runs/demo_final/` that has `baseline/rulebased/ai` subdirs, rerun `metrics.compare_three` and overwrite `summary.json`. **No simulation is run** — this recomputes from the committed telemetry. Run it; the january/july summaries now contain peak-demand and PMV fields retroactively.

**Validation:** in the regenerated summaries, january baseline `pmv_within_pct` should be high-but-not-perfect and directionally consistent with the temperature-band compliance already reported; a PMV that says 0% or 100% everywhere means an assumption bug (most likely clo-by-month or a unit slip). Compare AI vs baseline: the AI run may show slightly lower PMV compliance — report it honestly; the plan's honesty rule applies.

### Phase GC-4 — Agentic autonomy: self-correction loop + native tool-calling (2 h total, split)

**Purpose:** the Agentic Autonomy criterion (15%) rewards "effective and creative leverage of MCP protocols and self-correction loops." Two independent upgrades; 4a is mandatory and cheap, 4b is time-boxed.

#### GC-4a — Guardrail-feedback self-correction (20–30 min, do unconditionally)

- In `agent_runner.run_agent_session`, keep the previous cycle's `write_result` (which already contains `requested`, `applied`, `guardrail_notes`) in a local variable across loop iterations. Pass it into the LLM call as a new optional parameter, e.g. `llm_agent.propose(state, goals, history, previous_feedback=…)` with `None` on the first decision.
- In `controllers/llm_agent.py`, when `previous_feedback` is present and the previous request was clamped (applied ≠ requested or non-empty guardrail notes), render a short block into the user prompt: what was requested, what was actually applied, and why — phrased as "your previous decision was adjusted by the safety layer; account for this." When the previous decision was applied unmodified, say so in one line (positive feedback closes the loop too).
- This is a *literal, demonstrable self-correction loop*: the model observes the guardrail's correction of its own last action and adapts. It is visible in `decisions.jsonl` (clamped decision → next decision inside bounds), which is exactly the evidence the video and architecture doc will show.
- **Validation:** run a short AI session (one sim-day) with guardrail bounds temporarily printed; find at least one clamp event in the log and confirm the following decision respects the bound it was clamped to. Also confirm the first-decision path (no previous feedback) still works.

#### GC-4b — Native MCP tool-calling mode (60–90 min, HARD time-box; abandon cleanly at the box)

- Add a mode switch: `llm_agent.mode` in `config/default.yaml` (`structured` | `native`, default **stays `structured`**) plus a `--mode` CLI override in `agent_runner.py`. Nothing about structured mode changes.
- Native mode, inside `agent_runner`: at session start, fetch the tool list via the MCP session's `list_tools()` and translate each tool's name/description/JSON schema into the Ollama chat API's `tools` parameter format (the `ollama` pip client supports a `tools=` argument on `chat`). At each decision point, run a bounded agentic loop (max 6 tool rounds): send the conversation, if the model returns tool calls execute each against the live MCP session (`session.call_tool`) and append results as tool-role messages, repeat; terminate the decision successfully when `set_zone_setpoints` has been called (its result is the applied decision — record source `llm-native`). Failure conditions — no tool call in a round, unknown tool, invalid arguments, round cap hit, any exception — fall through to the **existing structured-mode path for that same decision** (source `structured-after-native-failure`), which itself still has the rule-based fallback behind it. Three nested safety nets; a native-mode bug can never lose a decision.
- Wall-clock reality: at 17–26 s per completion and 2–4 completions per decision, native mode costs 40–100 s per decision — potentially longer than the 60 s handshake timeout. Mitigation: when launching in native mode, `agent_runner` passes a larger `--timeout-s` (e.g., 180) to the spawned `mcp_server`. Use native mode ONLY for a short showcase run: **one simulated day (24 decisions) of the january period**, saved to `runs/demo_final/native_showcase/`, whose `decisions.jsonl` demonstrates genuine model-initiated tool sequences. All long runs stay in structured mode.
- **Validation:** the showcase run completes; its decision log shows ≥ 1 decision where the model called at least two read-tools before writing; count of `structured-after-native-failure` decisions is reported honestly in the run report dict (extend the existing counters).
- **Time-box rule:** if the Ollama tools-parameter path with the chosen model does not produce a first successful tool-call round within the first 30 min of GC-4b, stop, keep the mode switch scaffolding (it costs nothing), document "native mode implemented; model X's tool-calling proved unreliable, structured mode is the production configuration" in the architecture doc — that sentence with evidence is worth most of the same rubric credit.

### Phase GC-5 — Extended-horizon reliability run (15 min of code; ~4–5 h unattended)

**Purpose:** System Integration (30%, largest weight) asks for robustness "over an extended simulation time horizon"; the current evidence is two 1-week periods. **Exit criteria:** a completed AI-controlled **full-January (31-day)** run with its summary, decision log, and llm-vs-fallback counts committed as `runs/demo_final/extended_january/`.

Subtasks:

- **GC-5.1 `scripts/run_extended.sh`.** Captures the exact invocation: patch the IDF to Jan 1–Jan 31 via the existing orchestrator path, run baseline (fast, no LLM), then the AI run via `agent_runner` with `--period-days 31` and the config decision interval (60 sim-minutes ⇒ ~744 decisions). Wall-clock estimate at 17–26 s/decision: **3.5–5.4 h** — start it and walk away; it needs zero attention (that's the point: unattended autonomy is itself the reliability evidence).
- **GC-5.2 Launch it as early as possible** — right after GC-4a (so the extended run also exercises the self-correction loop), in a separate terminal, from a committed state (note the commit hash in `docs/decisions.md`). Do not run it in native mode. Do not touch `config/default.yaml` while it runs.
- **GC-5.3 On completion:** run `scripts/regenerate_summaries.py` (extend it to handle a baseline+ai-only period without a rulebased dir), commit `summary.json`, `decisions.jsonl`, the patched `building.idf`, and the agent_runner's final report (decisions made, llm vs fallback counts) — but **not** the month-long telemetry CSV if it exceeds a few MB; in that case commit a downsampled hourly version produced by a small addition to the regenerate script, and note the downsampling.
- **Failure handling:** if the run dies mid-month, the flushed-per-row telemetry and JSONL are intact up to the failure point — commit what completed with an honest note, and fall back to advertising the two-week evidence plus the partial. Do not burn hours rerunning.

**Validation:** `fallback_decisions / decisions_made` should be small (< 5%); zero crashes; summary numbers directionally consistent with january_week (similar savings %, comfort within a point or two). These three facts, stated with numbers, are the extended-horizon reliability proof for the architecture doc and slides.

### Phase GC-6 — Quantitative savings dashboard (1.5 h)

**Purpose:** the missing headline deliverable. Implement `dashboard/app.py` (currently a one-line comment) as a Streamlit app that is a **pure reader** of `runs/demo_final/` — it must never import from `abms.simulation`, `abms.mcp_server`, or anything that touches EnergyPlus; `abms.metrics`/`abms.carbon`/`abms.comfort` imports are fine (pure math). **Prerequisite:** GC-2 and GC-3 merged and `scripts/regenerate_summaries.py` run, so every `summary.json` already contains the peak-demand and PMV fields — the dashboard computes nothing that belongs in metrics.

Before writing any chart code, the coding agent must load the `dataviz` skill if available in its environment.

Contents, in build order:

- **GC-6.1 Data layer (20 min).** Discover period dirs under `runs/demo_final/` (any dir containing `summary.json`); load `summary.json`, each mode's `telemetry.csv` (pandas), and the AI run's `decisions.jsonl`. Cache with Streamlit's data-caching decorator keyed on file mtime. Tolerate missing modes (extended_january has no rulebased; native_showcase may exist) — every section must degrade gracefully rather than crash on a missing key, since summaries from different phases may have different field sets.
- **GC-6.2 Header + stat tiles (25 min).** Run/period selector (sidebar). Six tiles from `summary.json`: energy saved % (AI vs baseline), comfort compliance % (AI, with baseline's in small text), PMV compliance % (|PMV| ≤ 0.5), CO₂ avoided kg, peak-demand reduction kW/%, decisions made (with llm vs fallback split — the reliability number). Every tile's value must come from `summary.json` verbatim — no recomputation drift.
- **GC-6.3 Cumulative energy chart (20 min).** Baseline vs rulebased vs AI cumulative HVAC kWh over the period, straight from the `*_cumulative_kwh` telemetry columns (electricity+gas summed to match `total_hvac_kwh`); shade the baseline-vs-AI gap.
- **GC-6.4 Comfort + setpoint chart (20 min).** A selectable representative day: mean zone temp with the occupied comfort band shaded and the heating/cooling setpoint columns overlaid as step lines — this is where setpoint decisions visibly move the physics.
- **GC-6.5 Decision feed (15 min).** Scrollable table/list from `decisions.jsonl`: timestamp, source (llm/fallback), reasoning text, requested vs applied, guardrail notes highlighted when non-empty — the autonomy + self-correction evidence, judge-readable.
- **GC-6.6 Carbon shift chart (only if within budget).** The 24-h intensity profile from `abms.carbon` with AI vs baseline hourly electricity overlaid, showing load shifted into clean hours.

**Validation:** every displayed number equals its `summary.json` source; the app renders all committed periods including the mode-sparse ones without exceptions; run it once via `streamlit run dashboard/app.py` and screenshot for the README.

### Phase GC-7 — Indoor air quality via CO₂ (1–1.5 h + resim; **CONDITIONAL — do only if GC-1…GC-6 are done and ≥ 2 h remain before the coding hard stop**)

**Purpose:** the rubric's feedback list mentions IAQ; nothing in the current model tracks it. Minimal credible version: zone CO₂ concentration. This is the **only phase that touches the IDF and requires resimulating**, hence last and conditional.

Subtasks:

- **GC-7.1 IDF edits (`models/building.idf`):** add a `ZoneAirContaminantBalance` object with Carbon Dioxide Concentration = Yes and an Outdoor Carbon Dioxide Schedule (add a `Schedule:Constant` at 420 ppm, plus a `ScheduleTypeLimits` if none fits); People objects' CO₂ generation uses the E+ default rate — verify the field exists on this file's People objects, else leave default. Add the zone air CO₂ concentration output variable request. Consult the `.rdd` from a quick 2-day test run for the exact variable name string before wiring handles (the discover-handles script exists for exactly this).
- **GC-7.2 Pipeline:** `simulation.py` — one more per-zone variable handle (same acquire-or-hard-fail pattern as zone temps); `telemetry.py` — append `zone_co2_ppm_<Z>` ×5 to `FIELDNAMES` (this changes the frozen schema — every reader written in GC-6 must treat the columns as optional, which GC-6.1's graceful-degradation rule already guarantees for old runs); `metrics.py` — `co2_under_1000ppm_pct` over occupied zone-timesteps, added to summaries only when the columns exist; `mcp_server.py` — current CO₂ in `get_building_state`, 1,000 ppm threshold in `get_goals_and_constraints`; one line in the prompt.
- **GC-7.3 Resim:** rerun the two 1-week demo periods (baseline/rulebased/ai) with the updated IDF; regenerate summaries; recommit. Do NOT rerun extended_january.
- **Fallback if skipped (zero code):** one honest paragraph in the architecture doc — occupancy is tracked per zone, ventilation follows the model's fixed outdoor-air specification, CO₂ tracking was scoped out and is named future work. Decide at the checkpoint, not mid-task.

**Validation:** occupied-hours CO₂ in the 400–1,200 ppm range and rising/falling with occupancy; a flat 420 ppm everywhere means the contaminant balance isn't active (check the `.err` file).

### Phase GC-8 — Documentation deliverables (1 h; docs only, no code)

- **GC-8.1 `docs/architecture.md`** — fill the stub with the rubric-named subsections, in this order: (1) system overview with a mermaid flowchart (EnergyPlus ⇄ `SimulationRunner` ⇄ `SharedState`/`DecisionHandshake` ⇄ FastMCP tools ⇄ `agent_runner` ⇄ Ollama; guardrails and the two fallback layers drawn explicitly; dashboard as read-only observer of `runs/`); (2) a mermaid sequence diagram of one decision cycle; (3) **tool-calling architecture** — the five MCP tools, structured vs native modes, why structured is the production configuration (with the GC-4b evidence); (4) **prompt engineering strategy** — the system prompt's goal ordering, guardrail-feedback self-correction block, examples-driven iteration; (5) **prompt latency management** — the measured 17–26 s Ollama latency, the 60 s handshake timeout, both fallback layers, the decision-interval choice, keep-alive; (6) **handling lengthy simulation logs** — warmup/sizing filtering, why telemetry is a curated CSV rather than parsing `.eso`/`.mtr`, hourly aggregation in `get_recent_history`, the trailing-24 h window in `get_performance_so_far`, gitignore policy for raw E+ outputs; (7) metrics definitions incl. the PMV fixed assumptions and peak-demand threshold derivation; (8) extended-horizon reliability results (GC-5 numbers); (9) honest limitations (IAQ status per GC-7 outcome, MRT/RH assumptions, single climate).
- **GC-8.2 Re-scope the video script** in `docs/demo_script.md` from the old 5-min outline to **≤ 3 min**: 0:00–0:20 problem + architecture diagram; 0:20–1:10 live terminal decision cycles incl. one self-correction moment (clamp → adapted next decision); 1:10–2:10 dashboard tour (tiles → energy gap → PMV/comfort → decision feed); 2:10–2:40 reliability: extended-run numbers + guardrail/fallback design; 2:40–3:00 recap card + repo flash. Cut entirely relative to the 5-min version: the long architecture walkthrough (the diagram appears behind narration instead) and the limitations beat (moves to slides).
- **GC-8.3 Slides:** content outline only (the official template must be obtained by the user — flag this as a **user action, not a coding task**): title/team → problem → architecture diagram (reuse mermaid export) → closed-loop demo still → results table (energy %, PMV %, carbon kg, peak kW, decisions/fallbacks over 31 days) → autonomy evidence (decision-log excerpt) → limitations + future work.
- **GC-8.4 README refresh:** headline results from the regenerated summaries, dashboard screenshot, exact cold-start commands (including `scripts/run_extended.sh` and `streamlit run dashboard/app.py`), and the demo tag name.

---

## 3. Repository structure — delta only

New/changed relative to the existing tree (§0.2):

```
├── src/abms/
│   └── comfort.py                    # NEW — self-contained Fanger PMV (GC-3)
├── scripts/
│   ├── regenerate_summaries.py       # NEW — recompute summary.json from committed telemetry (GC-3.5)
│   └── run_extended.sh               # NEW — the 31-day extended run invocation (GC-5)
├── tests/
│   └── test_comfort.py               # NEW — PMV anchors, monotonicity (GC-3.4)
├── dashboard/app.py                  # REWRITTEN — Streamlit reader (GC-6)
├── runs/demo_final/
│   ├── extended_january/             # NEW artifact (GC-5)
│   └── native_showcase/              # NEW artifact, only if GC-4b succeeds
├── config/default.yaml               # +peak_demand_kw_threshold, +llm_agent.mode
├── prompts/controller_system.md      # +peak-demand paragraph, +PMV line, (+CO2 line if GC-7)
├── docs/architecture.md              # FILLED (GC-8.1)
├── docs/demo_script.md               # RE-SCOPED to ≤3 min (GC-8.2)
└── .gitignore                        # negation fix (GC-1.1)
```

Modified in place: `metrics.py` (GC-2.3, GC-3.2, GC-7.2), `mcp_server.py` (GC-2.4, GC-3.3, GC-7.2), `agent_runner.py` (GC-4a, GC-4b), `controllers/llm_agent.py` (GC-4a, GC-4b), `orchestrator.py` (GC-1.2), and — only if GC-7 runs — `simulation.py`, `telemetry.py`, `models/building.idf`.

---

## 4. Dependencies — delta only

**No new pip dependencies are required or wanted.** Specifically: PMV is implemented by hand (GC-3.1 rationale: unreliable network, ~40 lines of standard equations); native tool-calling uses the already-installed `ollama` client's `tools=` parameter; the dashboard uses the already-planned `streamlit`/`pandas`/`plotly` — if any of those three are not yet in the venv (dashboard was deferred), installing them is the only pip action in this plan. Everything else in §4 of `docs/PROJECT_PLAN.md` stands unchanged.

---

## 5. Timing, checkpoints, and the unattended-run schedule

| Phase | Attended effort | Wall-clock notes |
|---|---|---|
| GC-1 artifacts | 15 min | |
| GC-2 peak demand | 45 min | no resim |
| GC-3 PMV + regenerate | 1–1.5 h | no resim |
| GC-4a self-correction | 30 min | |
| GC-5 extended run | 15 min | **then 3.5–5.4 h unattended — LAUNCH BEFORE GC-6** |
| GC-6 dashboard | 1.5 h | runs while GC-5 executes |
| GC-4b native mode | 60–90 min time-boxed | optional; 30-min kill rule |
| GC-7 CO₂/IAQ | 1–1.5 h + ~30 min resim | conditional |
| GC-8 docs | 1 h | partly while GC-5 executes |
| **Attended total** | **≈ 5.5 h core (GC-1…6, 8) + ≈ 2.5 h optional (4b, 7)** | |

**Checkpoints:**
- **C1 (after GC-3):** regenerated summaries contain peak-demand + PMV fields and the numbers are sane. If GC-3's anchors won't converge within its budget, ship `pmv_within_pct` as the only PMV stat using a simplified-but-tested implementation, and move on.
- **C2 (GC-5 launch):** extended run started and confirmed producing decisions (watch the first 3–4 cycles, then leave it). If it won't start within 20 min of attention, run the two-week periods' story instead and reallocate the time to GC-6/GC-8.
- **C3 (before GC-4b/GC-7):** dashboard renders all committed runs and docs are drafted. Only then spend on the optional phases, video-deadline math permitting (the ≤3-min video + submission still need their protected ~2 h *after* the coding hard stop).

---

## 6. Testing and validation strategy

- **Regression gate for every phase:** `pytest` (existing `test_guardrails.py`, `test_decision_parsing.py`, plus new `test_comfort.py`) must pass, AND a 2-sim-day structured-mode AI smoke run must complete with zero fallback decisions before merging anything that touched `agent_runner.py`, `llm_agent.py`, or `mcp_server.py`. The smoke run is the real gate — the MCP surface has no unit tests by design.
- **Metrics changes (GC-2/GC-3):** validated against the *existing committed telemetry* via `regenerate_summaries.py` — this is deliberate: new metrics run against known-good data before any new simulation exists.
- **Schema discipline:** GC-7 is the only phase allowed to touch `telemetry.FIELDNAMES`, and only by appending; every telemetry reader (metrics, dashboard, MCP history) must tolerate the columns' absence for pre-GC-7 runs.
- **Self-correction (GC-4a):** evidence-based validation — find a real clamp→adapt pair in a short run's `decisions.jsonl`; if guardrails never trigger naturally, temporarily tighten `MAX_STEP_C` in a scratch config for the test run only.
- **Dashboard:** numbers cross-check against `summary.json` by construction (tiles read it verbatim); render-test on the mode-sparse dirs (extended_january, native_showcase).
- **No test may launch EnergyPlus** (unchanged rule); the smoke run above is manual.

---

## 7. Failure modes and descope ladder (this plan only)

1. **PMV implementation won't hit the ASHRAE anchors.** Most likely bugs: W vs met units, vapor-pressure formula, missing iteration on clothing surface temp. Time-box 30 min of debugging; then C1's simplified-implementation fallback.
2. **Native tool-calling flops** (likely with a 7–8B model). Already contained: 30-min kill rule, scaffolding kept, documented honestly — costs a stretch artifact, not the criterion.
3. **Extended run dies overnight/midway.** Flushed telemetry + JSONL survive; commit the partial with honest framing ("N days, M decisions, zero crashes until X"). Never rerun at the cost of dashboard/docs time.
4. **Regenerated summaries change headline numbers** (they shouldn't — energy/carbon math is untouched; only *new* fields are added). If any pre-existing field changes value, that's a regression in `metrics.py` — diff against the committed `summary.json` before overwriting; the regenerate script should print a field-level diff for exactly this reason (build that in).
5. **Dashboard time overruns.** Cut from the bottom of GC-6's build order (carbon chart first, then the comfort chart) — tiles + energy chart + decision feed are the minimum that satisfies "quantitative savings dashboard."
6. **Everything is tight.** Priority order to the rubric: GC-1 (free deliverable) → GC-6 (missing deliverable) → GC-5 (30% criterion) → GC-2/GC-3 (20% criterion) → GC-8 (deliverables) → GC-4a → GC-4b → GC-7. Note this differs from *execution* order only because execution order exists to feed the dashboard and start the long run early — if forced to drop, drop GC-7 first, then GC-4b, then GC-6.6/GC-6.4.

---

## 8. Git workflow for this plan

Follows the established repo convention (branch → PR → squash-merge per unit of work; Conventional Commits; this is a standing requirement for this repo, not optional):

- One branch/PR per phase: `feat/gc1-commit-run-artifacts`, `feat/gc2-peak-demand`, `feat/gc3-pmv`, `feat/gc4-self-correction` (4a and 4b may be separate PRs; 4b as `feat/gc4b-native-tools`), `feat/gc5-extended-run`, `feat/gc6-dashboard`, `feat/gc7-iaq-co2` (if run), `docs/gc8-architecture`.
- The GC-5 extended run must execute from a **merged, committed state** (record the hash); do not switch branches in the working tree while it runs — sequence the GC-6 dashboard work to happen on a branch created *before* launching the run, or in a separate worktree.
- Commit run artifacts (GC-1.3, GC-5.3) in dedicated commits so they're revertable independently of code.
- After GC-8: tag `v1.1-rubric` on the commit containing regenerated summaries + dashboard + docs; this supersedes `v1.0-demo` as the blessed demo state. Hard-stop coding at the tag; video and submission follow.

---

## 9. Adversarial pass — where this plan fails under pressure, revisions applied

1. **The extended run is the schedule's long pole and it's launched too late in a naive reading.** 3.5–5.4 h unattended means it MUST start by roughly the session's halfway point or it won't finish before the video hard stop. *Revision applied:* GC-5 is explicitly sequenced immediately after GC-4a (before the dashboard), C2 enforces it, and the partial-run fallback (7.3) makes a late or dead run survivable.
2. **Ordering trap: dashboard before metrics = double work.** *Revision applied:* hard prerequisite in GC-6 (summaries regenerated first) and the tiles-read-summary-verbatim rule, so metric changes never require dashboard edits.
3. **Schema freeze vs GC-7.** Appending CO₂ columns invalidates naive readers. *Revision applied:* GC-7 is last and conditional; graceful-degradation is a stated requirement of GC-6.1 *before* GC-7 exists; only appending is allowed.
4. **PMV anchor values are the one place this document could steer the coder wrong.** The two ASHRAE verification cases are standard but transcribed from memory. *Revision applied:* tolerance is ±0.15 not exact, the test's purpose is stated (catch unit/term bugs), and the C1 fallback exists. If both anchors fail symmetrically by the same offset, suspect the anchor transcription before the code — and say so in the PR.
5. **Native mode can silently eat the handshake timeout.** A 100 s decision against a 60 s timeout means every native decision falls back and the showcase is worthless while *looking* like it ran. *Revision applied:* GC-4b explicitly raises `--timeout-s` to 180 for native sessions and counts `structured-after-native-failure` decisions in the run report, making the failure visible instead of silent.
6. **Regeneration could corrupt the already-good committed results.** *Revision applied:* failure-mode 4's field-level diff requirement in `regenerate_summaries.py` — pre-existing fields must be byte-identical; only additions are expected.
7. **Scope temptation:** six phases touch `mcp_server.py`/prompt — each adds "one line." Cumulative prompt drift can degrade the already-tuned controller. *Revision applied:* the 2-day zero-fallback smoke run is a mandatory merge gate for every phase touching the agent path (§6), and prompt additions are limited to the single paragraphs/lines specified — no rewrites.

**Handover protocol:** implement one phase at a time in the §1 execution order. Along with each phase's section, always provide §0 (ground truth) and §6 (testing gates) as standing context. Do not start the next phase until the current phase's named validation evidence exists. GC-5's unattended window is when GC-6 and GC-8 happen — plan the session around that overlap.
