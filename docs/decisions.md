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
  6 decimal places, far inside the ~1% tolerance.
