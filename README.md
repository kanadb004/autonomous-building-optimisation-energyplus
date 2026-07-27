# Autonomous Building Optimisation

An autonomous Building Management System. EnergyPlus simulates a building,
an open-source LLM served by Ollama makes HVAC setpoint decisions through an
MCP server, deterministic guardrails validate every decision, and a
Streamlit dashboard compares AI-controlled operation against the baseline.

**Demo video:** [`runs/demo_video/kanad-bhattacharya_honeywell.mov`](runs/demo_video/kanad-bhattacharya_honeywell.mov)
(also on [Google Drive](https://drive.google.com/file/d/1iaASAQGhxvRtMleT-ByD2kZ1FKTcWOGY/view?usp=sharing)).

See [`docs/architecture.md`](docs/architecture.md) for how the pieces fit
together and [`docs/decisions.md`](docs/decisions.md) for the design
decisions and why they were made.

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
ollama pull qwen2.5:3b-instruct   # or set OLLAMA_MODEL to a model you already have
```

## Running it

Baseline vs rule-based vs AI. Patches the run period, runs all three
controllers, writes `summary.json`:

```bash
python -m abms.orchestrator demo   # both periods from config/default.yaml
```

Just the AI loop, with the decision cycles scrolling in the terminal:

```bash
python -m abms.agent_runner \
  --idf models/building.idf --epw models/weather/USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw \
  --run-id demo --output-dir runs/demo/ai --period-days 7
```

Dashboard. Reads the committed `runs/demo_final/` telemetry and never
touches EnergyPlus:

```bash
uv pip install -r requirements-dashboard.txt   # first time only
streamlit run dashboard/app.py
```

## Results (`runs/demo_final/`, AI vs baseline)

| Period | Energy saved | Carbon avoided | Comfort compliance |
| --- | --- | --- | --- |
| January (heating-dominated) | 3.1% | 2.7% | 95.9% (baseline 100%) |
| July (cooling-dominated) | 16.1% | 7.8% | 100% (baseline 100%) |

The rule-based controller beats the LLM on raw January savings, 8.0% against
3.1%. That result is left as it is rather than tuned away: the LLM spends
some of that margin on comfort headroom and on pre-heating decisions it can
explain, instead of a fixed occupancy setback. The dashboard's decision feed
shows the reasoning behind individual choices.

## Reliability

Every proposed setpoint passes through the guardrail layer
(`src/abms/guardrails.py`) before EnergyPlus applies it: actuator bounds,
max step per decision, minimum deadband, and an occupied-hours comfort floor
and ceiling. A 60s handshake timeout plus a rule-based fallback mean a run
can't stall or apply an unsafe setpoint even if Ollama is unreachable or
returns nonsense. Clamps are fed back to the LLM so it can adapt on the next
decision.

A 31-day unattended run (`runs/demo_final/extended_january/`) exercised all
of this end to end. Tests: `pytest tests/`.

## Tags

`v0.2-closed-loop-rulebased`, `v0.3-mcp`, `v0.4-ai-loop`. `v1.0-demo` marks
the commit the demo video was recorded against.

## Limitations

The model is `qwen2.5:3b-instruct`, small enough that it sometimes trades
savings for comfort margin, and the rule-based controller still beats it on
January energy. Decisions are structured JSON rather than native tool calls.
There is one building and one climate, not a portfolio.
