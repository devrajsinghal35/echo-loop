"""
EnergyPlus runner service.

Provides two execution modes:
  1. run_subprocess() — runs the energyplus CLI as a child process
  2. run_api()        — runs via the Python API (pyenergyplus) with callbacks

Both modes capture stdout/stderr to log files and copy EnergyPlus output
artefacts (ESO, CSV, SQL, HTML) into the designated output directory.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable

from simulation.config import (
    LOGS_DIR,
    ensure_pyenergyplus_on_path,
    get_energyplus_dir,
    get_energyplus_exe,
)

# EnergyPlus output files we want to preserve
_OUTPUT_EXTENSIONS = {
    ".eso", ".csv", ".sql", ".htm", ".html",
    ".err", ".eio", ".rdd", ".mdd", ".mtd",
    ".shd", ".dxf", ".audit", ".bnd",
}


# ── helpers ──────────────────────────────────────────────────────────────

def _prepare_output_dir(output_dir: Path) -> Path:
    """Ensure the output directory exists."""
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _collect_outputs(run_dir: Path, output_dir: Path) -> list[Path]:
    """Copy EnergyPlus output files from *run_dir* into *output_dir*."""
    collected: list[Path] = []
    for f in run_dir.iterdir():
        if f.suffix.lower() in _OUTPUT_EXTENSIONS:
            dest = output_dir / f.name
            shutil.copy2(f, dest)
            collected.append(dest)
    return collected


# ── subprocess mode ──────────────────────────────────────────────────────

def run_subprocess(
    idf_path: str | Path,
    epw_path: str | Path,
    output_dir: str | Path | None = None,
) -> dict:
    """
    Execute EnergyPlus via the CLI as a subprocess.

    Parameters
    ----------
    idf_path : path to the .idf model file
    epw_path : path to the .epw weather file
    output_dir : directory for logs and outputs (defaults to LOGS_DIR)

    Returns
    -------
    dict with keys: exit_code, stdout_log, stderr_log, output_files, duration_s
    """
    idf_path = Path(idf_path).resolve()
    epw_path = Path(epw_path).resolve()
    output_dir = _prepare_output_dir(Path(output_dir) if output_dir else LOGS_DIR)

    exe = get_energyplus_exe()

    # Use a temp directory as the E+ working dir so outputs don't clutter
    with tempfile.TemporaryDirectory(prefix="eplus_run_") as tmpdir:
        cmd = [
            str(exe),
            "-w", str(epw_path),
            "-d", tmpdir,
            "-r",           # generate CSV from ESO
            str(idf_path),
        ]

        stdout_log = output_dir / "energyplus_stdout.log"
        stderr_log = output_dir / "energyplus_stderr.log"

        t0 = datetime.now()

        with open(stdout_log, "w") as fout, open(stderr_log, "w") as ferr:
            proc = subprocess.run(
                cmd,
                stdout=fout,
                stderr=ferr,
                cwd=tmpdir,
            )

        duration = (datetime.now() - t0).total_seconds()

        # Collect outputs
        output_files = _collect_outputs(Path(tmpdir), output_dir)

    return {
        "exit_code": proc.returncode,
        "stdout_log": str(stdout_log),
        "stderr_log": str(stderr_log),
        "output_files": [str(f) for f in sorted(output_files)],
        "duration_s": round(duration, 2),
    }


# ── API mode ─────────────────────────────────────────────────────────────

def run_api(
    idf_path: str | Path,
    epw_path: str | Path,
    output_dir: str | Path | None = None,
    callbacks: dict[str, Callable] | None = None,
) -> dict:
    """
    Execute EnergyPlus via the Python API (pyenergyplus).

    Parameters
    ----------
    idf_path : path to the .idf model file
    epw_path : path to the .epw weather file
    output_dir : directory for logs and outputs (defaults to LOGS_DIR)
    callbacks : optional dict mapping callback names to callables.
        Recognised keys:
          - "begin_timestep"           → callback_begin_system_timestep_before_predictor
          - "after_predictor"          → callback_after_predictor_after_hvac_managers
          - "end_zone_timestep"        → callback_end_zone_timestep_after_zone_reporting

    Returns
    -------
    dict with keys: exit_code, output_files, duration_s
    """
    ensure_pyenergyplus_on_path()
    from pyenergyplus.api import EnergyPlusAPI  # type: ignore[import-untyped]

    idf_path = Path(idf_path).resolve()
    epw_path = Path(epw_path).resolve()
    output_dir = _prepare_output_dir(Path(output_dir) if output_dir else LOGS_DIR)

    api = EnergyPlusAPI()
    state = api.state_manager.new_state()

    # Register stdout/stderr capture
    stdout_log = output_dir / "energyplus_stdout.log"
    stderr_log = output_dir / "energyplus_stderr.log"

    stdout_fh = open(stdout_log, "wb")
    stderr_fh = open(stderr_log, "wb")

    def _stdout_cb(msg) -> None:
        if isinstance(msg, str):
            msg = msg.encode("utf-8")
        stdout_fh.write(msg)
        stdout_fh.flush()

    def _stderr_cb(msg) -> None:
        if isinstance(msg, str):
            msg = msg.encode("utf-8")
        stderr_fh.write(msg)
        stderr_fh.flush()

    api.runtime.callback_message(state, _stdout_cb)

    # Register user callbacks
    _cb_map = {
        "begin_timestep": api.runtime.callback_begin_system_timestep_before_predictor,
        "after_predictor": api.runtime.callback_after_predictor_after_hvac_managers,
        "end_zone_timestep": api.runtime.callback_end_zone_timestep_after_zone_reporting,
    }
    if callbacks:
        for name, fn in callbacks.items():
            if name in _cb_map:
                _cb_map[name](state, fn)
            else:
                raise ValueError(
                    f"Unknown callback '{name}'. Choose from: {list(_cb_map.keys())}"
                )

    # Build the CLI args for the API runner
    run_args = [
        "-w", str(epw_path),
        "-d", str(output_dir),
        "-r",
        str(idf_path),
    ]

    t0 = datetime.now()
    exit_code = api.runtime.run_energyplus(state, run_args)
    duration = (datetime.now() - t0).total_seconds()

    stdout_fh.close()
    stderr_fh.close()

    # Gather output files
    output_files = [
        str(f) for f in sorted(output_dir.iterdir())
        if f.suffix.lower() in _OUTPUT_EXTENSIONS
    ]

    # Clean up API state
    api.state_manager.delete_state(state)

    return {
        "exit_code": exit_code,
        "stdout_log": str(stdout_log),
        "stderr_log": str(stderr_log),
        "output_files": output_files,
        "duration_s": round(duration, 2),
    }
