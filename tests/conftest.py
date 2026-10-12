"""Load the protocol package without executing HA integration setup."""

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("cube_test")
package.__path__ = [str(ROOT / "custom_components" / "segway_cube")]
sys.modules["cube_test"] = package
