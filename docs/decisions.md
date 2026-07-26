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
- **Ollama latency measurement:** TODO — fill in after `scripts/smoke_ollama.py`
  runs successfully (drives the Phase 4 decision-interval choice).
