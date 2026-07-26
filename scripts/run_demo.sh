#!/usr/bin/env bash
# The command sequence used for the demo, documented as a script.
#
# Don't run it end to end unattended: the live loop is meant to be stopped
# with Ctrl+C once enough cycles have run, and the dashboard stays in the
# foreground. See docs/demo_script.md.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# abms lives in src/ and isn't pip-installed.
export PYTHONPATH="$REPO_ROOT/src"

echo "[run_demo] pre-flight"
ollama list | grep -q qwen2.5:3b-instruct
ollama run qwen2.5:3b-instruct "hi" >/dev/null
python scripts/smoke_energyplus_api.py
python scripts/smoke_ollama.py

echo "[run_demo] live loop: Ctrl+C once several cycles have run"
python -m abms.agent_runner \
  --idf models/building.idf \
  --epw models/weather/USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw \
  --run-id demo_video \
  --output-dir runs/demo_video/ai \
  --period-days 7

echo "[run_demo] dashboard: run this in a second terminal"
echo "    streamlit run dashboard/app.py"

echo "[run_demo] guardrail evidence, from the committed extended run:"
grep -B1 "guardrail_notes=\['" runs/demo_final/extended_january/agent_runner_report.log | head -4

echo "[run_demo] cleanup after recording:"
echo "    rm -rf runs/demo_video/"
