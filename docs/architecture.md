# System Architecture

An open-source LLM controls HVAC setpoints in an EnergyPlus 5-zone office
model through an MCP tool surface, with a deterministic guardrail layer
between the model and the physics engine.

## 1. Component overview

```mermaid
flowchart LR
    subgraph Physics["EnergyPlus (physics engine)"]
        SIM["Simulation thread\nsrc/abms/simulation.py\n(EnergyPlus C API callbacks)"]
    end

    subgraph Bridge["Shared process"]
        STORE["SharedState datastore\nsrc/abms/datastore.py"]
        HANDSHAKE["DecisionHandshake\nsrc/abms/decision_handshake.py\n(60s timeout -> rule-based fallback)"]
        MCP["MCP server (FastMCP, stdio)\nsrc/abms/mcp_server.py\n5 tools"]
    end

    subgraph Client["Agent runner process"]
        RUNNER["agent_runner.py\nMCP client loop"]
        LLM["LLM agent\ncontrollers/llm_agent.py\n(Ollama, qwen2.5:3b-instruct)"]
        FALLBACK["Rule-based fallback\ncontrollers/rulebased.py"]
    end

    GUARD["Guardrails\nsrc/abms/guardrails.py\n(hard bounds, max step, deadband,\noccupied comfort floor/ceiling)"]

    SIM -- "zone temp, occupancy,\nHVAC power, sim time" --> STORE
    STORE --> MCP
    MCP -- "get_building_state\nget_recent_history\nget_goals_and_constraints" --> RUNNER
    RUNNER --> LLM
    LLM -- "heating_c, cooling_c,\nreasoning" --> RUNNER
    RUNNER -- "set_zone_setpoints" --> MCP
    MCP --> HANDSHAKE
    HANDSHAKE --> GUARD
    GUARD -- "clamped setpoints" --> HANDSHAKE
    HANDSHAKE -- "applied setpoints" --> SIM
    HANDSHAKE -. "on timeout or malformed/\nunreachable LLM" .-> FALLBACK
    FALLBACK -.-> HANDSHAKE
```

Two processes talk over MCP on stdio. The simulation process runs
EnergyPlus inside `abms.mcp_server`, sharing a `SharedState` and a
`DecisionHandshake` with the sim thread. The agent runner is the MCP client:
it polls state, asks the LLM for a decision, and writes it back.
Every write passes through `guardrails.py` before EnergyPlus sees it: the
LLM proposes, the guardrails dispose.

## 2. Sequence: one decision cycle

```mermaid
sequenceDiagram
    participant EP as EnergyPlus (sim thread)
    participant DS as SharedState / Handshake
    participant MCP as MCP server
    participant AR as agent_runner
    participant LLM as LLM agent (Ollama)
    participant GR as Guardrails

    EP->>DS: zone temps, occupancy, HVAC power, sim_datetime
    EP->>DS: awaiting_decision = true (decision point reached)
    AR->>MCP: get_building_state()
    MCP->>DS: read latest snapshot
    DS-->>AR: temps, occupancy, PMV, current setpoints, current_demand_kw
    AR->>MCP: get_goals_and_constraints()
    MCP-->>AR: comfort band, guardrail bounds, peak-demand threshold, carbon forecast
    AR->>MCP: get_recent_history(hours)
    MCP-->>AR: hourly-aggregated trend
    AR->>LLM: propose(state, goals, history, previous_feedback)
    alt Ollama reachable, valid JSON
        LLM-->>AR: heating_c, cooling_c, reasoning
    else timeout / malformed / unreachable
        AR->>AR: rule-based fallback decision + reasoning string
    end
    AR->>MCP: set_zone_setpoints(heating_c, cooling_c, reasoning)
    MCP->>DS: submit_decision()
    DS->>GR: clamp(requested)
    GR-->>DS: applied setpoints + guardrail_notes
    DS-->>EP: applied heating/cooling setpoints (next timestep)
    DS-->>MCP: requested, applied, guardrail_notes
    MCP-->>AR: accepted, requested, applied, guardrail_notes
    AR->>AR: log cycle, feed guardrail_notes back as previous_feedback
```

The handshake's 60s timeout is the second line of defence. If the agent
runner dies or hangs mid-cycle, the sim thread applies the same rule-based
decision it would have used anyway, so a run can't stall waiting on the LLM.

## 3. Tool-calling architecture

### 3.1 The five MCP tools (`src/abms/mcp_server.py`)

Five tools: four reads and one write. The cap is deliberate. A small local
model degrades as the tool list grows, and every field in every response
competes for the same context budget.

| Tool | Purpose |
| --- | --- |
| `get_building_state` | Per-zone temp/occupancy/PMV, outdoor temp, current setpoints, current HVAC demand, sim time, `awaiting_decision`. Called first every cycle. |
| `get_recent_history` | Hourly-aggregated trend over the last N sim-hours (temp, energy, occupancy). |
| `get_goals_and_constraints` | Objectives (energy, carbon, peak demand), comfort/PMV band, guardrail bounds, decision cadence, carbon-intensity forecast. |
| `set_zone_setpoints` | Write a decision; only valid while `awaiting_decision`. Returns requested vs applied values and clamp notes. |
| `get_performance_so_far` | Cumulative energy, trailing-24h comfort and carbon, decision count. A mid-run sanity check for the agent. |

## Guardrail layer (`src/abms/guardrails.py`, mirrored in `config/default.yaml`)

Deterministic, never LLM-mediated: actuator bounds (heating 12-23 C,
cooling 22-32 C), a minimum 1 C deadband, a maximum 3 C step per decision,
and an occupied-hours floor and ceiling of 20-26 C that overrides the looser
bounds whenever the building is occupied.

Every clamp is logged with a reason and fed back to the LLM on the next
cycle, so repeated out-of-bounds proposals get corrected without a human
stepping in.

## Design-decision log

See [`decisions.md`](decisions.md) for the dated log of non-obvious
implementation choices: model selection, API gotchas, threshold
derivations.
