# TODO (mirrors docs/PROJECT_PLAN.md §2 phase breakdown)

Checked off per commit. One GitHub Issue per phase also exists (§10.3).

## Phase 0 — Environment, repo, and toolchain bootstrap
- [x] 0.1 Create GitHub repo + local clone
- [x] 0.2 Python environment (3.12 venv, ENERGYPLUS_DIR path setup)
- [x] 0.3 Verify pyenergyplus import + trivial API run
- [x] 0.4 Install and verify Ollama + model
- [x] 0.5 Install remaining Python deps + freeze

## Phase 1 — Python API harness: read live state from a running simulation
- [x] 1.1 Choose and prepare the building model
- [x] 1.2 Simulation wrapper class
- [x] 1.3 Variable/meter handle acquisition
- [x] 1.4 Warmup/sizing filtering + timestep bookkeeping
- [x] 1.5 Telemetry logger

## Phase 2 — Actuation, baseline vs controlled, rule-based controller
- [x] 2.1 Actuator acquisition
- [x] 2.2 Controller interface
- [x] 2.3 Decision-interval gating
- [x] 2.4 Guardrail validator
- [x] 2.5 Run orchestrator + metrics
- [x] 2.6 Decision log

## Phase 3 — MCP server
- [ ] 3.1 Shared state store
- [ ] 3.2 Tool definitions
- [ ] 3.3 Decision handshake
- [ ] 3.4 Manual MCP test

## Phase 4 — LLM agent and full closed loop
- [ ] 4.1 Agent runner
- [ ] 4.2 System prompt engineering
- [ ] 4.3 Reasoning capture
- [ ] 4.4 Robustness hardening
- [ ] 4.5 Full comparison runs
- [ ] 4.6 Tuning pass

## Phase 5 — Savings dashboard
- [ ] Data-loading layer
- [ ] Stat tiles + energy chart
- [ ] Comfort/setpoint chart
- [ ] Decision feed
- [ ] Polish

## Phase 6 — Documentation and architecture
- [ ] architecture.md (mermaid diagrams, design-decision log)
- [ ] README cold-start instructions
- [ ] Honest limitations section

## Phase 7 — Demo video + submission (outside coding budget)
- [ ] Shot list recorded per §9
- [ ] Tag v1.0-demo
- [ ] Submit
