"""trs: Official CLI + Python SDK for The Room System."""
__version__ = "0.1.0"

from .client import TrsClient, TrsError
from .config import Config, load_config, save_config

__all__ = ["TrsClient", "TrsError", "Config", "load_config", "save_config", "__version__"]
