# Honeywell Campus Connect — Autonomous Building Optimization

An AI-powered autonomous Building Management System: EnergyPlus simulates a
building, an open-source LLM (via Ollama) makes HVAC setpoint decisions
through an MCP server, deterministic guardrails validate every decision, and
a Streamlit dashboard compares AI-controlled vs baseline operation.

**Status:** hackathon in progress — Phase 0 (environment bootstrap) complete.

See `docs/PROJECT_PLAN.md` for the full plan and `docs/decisions.md` for the
running design-decision log.

## Setup (macOS)

Requires EnergyPlus 26.1.0 installed at `/Applications/EnergyPlus-26-1-0`,
Python 3.12, and [Ollama](https://ollama.com).

```bash
cp .env.example .env   # edit if your EnergyPlus install path differs
uv venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements.txt
python scripts/smoke_energyplus_api.py
python scripts/smoke_ollama.py
```
