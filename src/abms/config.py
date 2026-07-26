"""Environment + config loading: resolves ENERGYPLUS_DIR and puts pyenergyplus
on sys.path so it imports from the EnergyPlus install itself (guarantees
dylib/version match), rather than from a pip package. Also loads
`config/default.yaml` (§4 Phase 4 -- the demo period and LLM agent settings
are config values, not hardcoded)."""

import os
import sys
from pathlib import Path

import yaml

DEFAULT_ENERGYPLUS_DIR = "/Applications/EnergyPlus-26-1-0"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "default.yaml"


def get_energyplus_dir() -> Path:
    return Path(os.environ.get("ENERGYPLUS_DIR", DEFAULT_ENERGYPLUS_DIR))


def ensure_pyenergyplus_on_path() -> Path:
    """Add the EnergyPlus install dir to sys.path so `import pyenergyplus`
    resolves to the version-matched bundled copy. Returns the resolved dir."""
    ep_dir = get_energyplus_dir()
    ep_dir_str = str(ep_dir)
    if ep_dir_str not in sys.path:
        sys.path.insert(0, ep_dir_str)
    return ep_dir


def load(config_path=DEFAULT_CONFIG_PATH) -> dict:
    """Loads `config/default.yaml`. Not cached -- this is called at most
    once per process (orchestrator/agent_runner startup), so a module-level
    cache would only add stale-config risk for no measurable benefit."""
    return yaml.safe_load(Path(config_path).read_text())


def llm_agent_config(config_path=DEFAULT_CONFIG_PATH) -> dict:
    """The `llm_agent` section of the config, with OLLAMA_MODEL/OLLAMA_HOST
    env vars overriding the yaml defaults if set (§1.2: the controller must
    be model-agnostic, swappable without a code change)."""
    cfg = dict(load(config_path)["llm_agent"])
    if os.environ.get("OLLAMA_MODEL"):
        cfg["model"] = os.environ["OLLAMA_MODEL"]
    if os.environ.get("OLLAMA_HOST"):
        cfg["host"] = os.environ["OLLAMA_HOST"]
    return cfg
