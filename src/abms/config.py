"""Environment + config loading: resolves ENERGYPLUS_DIR and puts pyenergyplus
on sys.path so it imports from the EnergyPlus install itself (guarantees
dylib/version match), rather than from a pip package."""

import os
import sys
from pathlib import Path

DEFAULT_ENERGYPLUS_DIR = "/Applications/EnergyPlus-26-1-0"


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
