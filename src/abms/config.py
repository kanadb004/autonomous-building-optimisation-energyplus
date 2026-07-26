"""Environment and config loading.

Puts pyenergyplus on sys.path from the EnergyPlus install rather than a
pip package, so the Python module and the dylib always match. Also loads
config/default.yaml.
"""

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
    """Put the EnergyPlus install dir on sys.path and return it."""
    ep_dir = get_energyplus_dir()
    ep_dir_str = str(ep_dir)
    if ep_dir_str not in sys.path:
        sys.path.insert(0, ep_dir_str)
    return ep_dir


def load(config_path=DEFAULT_CONFIG_PATH) -> dict:
    """Load the config. Not cached; it's read once per process."""
    return yaml.safe_load(Path(config_path).read_text())


def llm_agent_config(config_path=DEFAULT_CONFIG_PATH) -> dict:
    """The llm_agent config section, with OLLAMA_MODEL and OLLAMA_HOST
    overriding the yaml if they're set."""
    cfg = dict(load(config_path)["llm_agent"])
    if os.environ.get("OLLAMA_MODEL"):
        cfg["model"] = os.environ["OLLAMA_MODEL"]
    if os.environ.get("OLLAMA_HOST"):
        cfg["host"] = os.environ["OLLAMA_HOST"]
    return cfg
