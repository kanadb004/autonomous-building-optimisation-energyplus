#!/usr/bin/env bash
# Full-January reliability run. Patches the RunPeriod to Jan 1-31, runs the
# fast baseline, then the AI run in structured mode.
#
# That's about 744 decisions, so the AI leg takes 3-5 hours. Start it and
# leave it alone.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT/src"

RUN_ID="extended_january"
OUTPUT_DIR="runs/demo_final/${RUN_ID}"
PATCHED_IDF="${OUTPUT_DIR}/building.idf"
WEATHER="models/weather/USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw"

mkdir -p "$OUTPUT_DIR"

echo "[run_extended] patching models/building.idf to Jan 1-31 -> ${PATCHED_IDF}"
python -c "
from pathlib import Path
from abms import idf_utils
idf_utils.with_run_period(Path('models/building.idf'), 1, 1, 1, 31, Path('${PATCHED_IDF}'))
"

echo "[run_extended] writing model-provenance manifest"
python -c "
import hashlib, json
from pathlib import Path
source = Path('models/building.idf')
manifest = {
    'source_idf': 'models/building.idf',
    'source_idf_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
    'patched_idf': 'building.idf',
}
Path('${OUTPUT_DIR}/manifest.json').write_text(json.dumps(manifest, indent=2) + chr(10))
"

echo "[run_extended] baseline run (fast, no LLM) -> ${OUTPUT_DIR}/baseline"
python -c "
from pathlib import Path
from abms import config
config.ensure_pyenergyplus_on_path()
from abms.orchestrator import run_single
run_single('baseline', Path('${OUTPUT_DIR}'), '${RUN_ID}', Path('${PATCHED_IDF}'), Path('${WEATHER}'))
"

echo "[run_extended] AI run (structured mode, 31 days) -> ${OUTPUT_DIR}/ai"
python -m abms.agent_runner \
    --idf "$PATCHED_IDF" \
    --epw "$WEATHER" \
    --run-id "$RUN_ID" \
    --output-dir "${OUTPUT_DIR}/ai" \
    --period-days 31 \
    | tee "${OUTPUT_DIR}/agent_runner_report.log"

echo "[run_extended] done."
