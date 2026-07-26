"""
EnergyPlus simulation layer — configuration.

Centralises all paths (EnergyPlus install dir, IDF model, weather file,
output directory) and provides validation helpers.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Directory layout
# ---------------------------------------------------------------------------
SIMULATION_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SIMULATION_DIR.parent

MODELS_DIR = SIMULATION_DIR / "models"
WEATHER_DIR = SIMULATION_DIR / "weather"
LOGS_DIR = SIMULATION_DIR / "logs"

# Default file paths
IDF_PATH = MODELS_DIR / "baseline_office.idf"
EPW_PATH = WEATHER_DIR / "chicago.epw"

# ---------------------------------------------------------------------------
# EnergyPlus installation auto-detection
# ---------------------------------------------------------------------------
_CANDIDATE_DIRS: list[str] = [
    # macOS standard locations
    "/Applications/EnergyPlus-24-2-0",
    "/Applications/EnergyPlus-24.2.0",
    # tar.gz extraction targets
    os.path.expanduser("~/EnergyPlus-24-2-0"),
    os.path.expanduser("~/EnergyPlus-24.2.0"),
    # Linux typical
    "/usr/local/EnergyPlus-24-2-0",
    "/usr/local/EnergyPlus-24.2.0",
]


def _detect_energyplus_dir() -> Path | None:
    """Return the first existing EnergyPlus installation directory."""
    # 1. Environment variable override
    env = os.environ.get("ENERGYPLUS_DIR")
    if env:
        p = Path(env)
        if p.is_dir():
            return p

    # 2. Probe well-known locations
    for candidate in _CANDIDATE_DIRS:
        p = Path(candidate)
        if p.is_dir():
            return p

    return None


ENERGYPLUS_DIR: Path | None = _detect_energyplus_dir()


def get_energyplus_dir() -> Path:
    """Return validated EnergyPlus installation directory or raise."""
    if ENERGYPLUS_DIR is None:
        raise EnvironmentError(
            "EnergyPlus installation not found.  Set the ENERGYPLUS_DIR "
            "environment variable or install EnergyPlus to one of:\n  "
            + "\n  ".join(_CANDIDATE_DIRS)
        )
    return ENERGYPLUS_DIR


def get_energyplus_exe() -> Path:
    """Return path to the ``energyplus`` executable."""
    d = get_energyplus_dir()
    exe = d / "energyplus"
    if not exe.exists():
        raise FileNotFoundError(f"energyplus binary not found at {exe}")
    return exe


def ensure_pyenergyplus_on_path() -> None:
    """Add EnergyPlus dir to ``sys.path`` so ``import pyenergyplus`` works."""
    d = str(get_energyplus_dir())
    if d not in sys.path:
        sys.path.insert(0, d)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_all() -> dict[str, bool]:
    """Check every required resource and return a status dict."""
    checks: dict[str, bool] = {}

    checks["energyplus_installed"] = ENERGYPLUS_DIR is not None
    if ENERGYPLUS_DIR:
        checks["energyplus_exe"] = (ENERGYPLUS_DIR / "energyplus").exists()
    else:
        checks["energyplus_exe"] = False

    checks["idf_exists"] = IDF_PATH.exists()
    checks["epw_exists"] = EPW_PATH.exists()
    checks["logs_dir"] = LOGS_DIR.is_dir()

    return checks


def print_status() -> None:
    """Print a human-readable validation report."""
    checks = validate_all()
    print("\n=== EnergyPlus Configuration ===")
    print(f"  EnergyPlus dir : {ENERGYPLUS_DIR or 'NOT FOUND'}")
    print(f"  IDF model      : {IDF_PATH}")
    print(f"  Weather file   : {EPW_PATH}")
    print(f"  Output dir     : {LOGS_DIR}")
    print()
    all_ok = True
    for name, ok in checks.items():
        status = "✅" if ok else "❌"
        print(f"  {status} {name}")
        if not ok:
            all_ok = False
    print()
    if all_ok:
        print("  All checks passed — ready to run.\n")
    else:
        print("  Some checks failed — see above.\n")


if __name__ == "__main__":
    print_status()
