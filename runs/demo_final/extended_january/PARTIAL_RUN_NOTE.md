# Extended-horizon run (GC-5) — partial, stopped deliberately

**Status: partial, stopped intentionally mid-run, not a crash.** Full detail
and rationale in `docs/decisions.md` under "2026-07-26 — GC-5 partial-run
stop". Summary for anyone browsing this directory directly:

- **Baseline** (`baseline/`): completed the full January period (1/1-1/31,
  2976 zone-timesteps) successfully, no LLM involved.
- **AI** (`ai/`): stopped after **172 decisions**, **0 fallbacks/alerts**,
  covering `1986-01-01T00:15` through `1986-01-08T06:45` (~7.3 of 31 days,
  ~23% of the ~746-decision target) via SIGINT for a clean shutdown —
  `decisions.jsonl` and `telemetry.csv` are flushed per-row/per-decision so
  everything up to that point is intact and uncorrupted.
- **`summary.json`'s `comparison.ai_vs_baseline` block is NOT a valid
  energy/carbon savings comparison** — it divides a full-month baseline
  against a ~7.3-day AI run, so the ~73% figures reflect the period-length
  mismatch, not model performance. Do not cite those percentages. The valid
  evidence from this run is **reliability**, not savings: 172/172 decisions
  resolved through the LLM with zero runner-side or handshake fallbacks
  over the covered window — the reliability proof GC-5 exists to produce,
  just over a shorter horizon than the full 31 days.
