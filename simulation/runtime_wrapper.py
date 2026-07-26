"""
EnergyPlus runtime wrapper.

Provides ``read_variable(name)`` and ``set_actuator(name, value)`` that
work during a live EnergyPlus simulation via the Python API.

Usage
-----
::

    from simulation.runtime_wrapper import EnergyPlusRuntime

    rt = EnergyPlusRuntime()

    # Register what you want to read / control
    rt.register_variable("zone_temp", "Zone Mean Air Temperature", "Office Zone")
    rt.register_variable("outdoor_temp", "Site Outdoor Air Drybulb Temperature", "Environment")
    rt.register_actuator(
        "cooling_setpoint",
        "Schedule:Constant",
        "Schedule Value",
        "Cooling Setpoint Schedule",
    )

    # Run — callbacks are invoked every timestep automatically
    result = rt.run("path/to/model.idf", "path/to/weather.epw")

    # After simulation, inspect captured timeseries
    print(rt.get_timeseries("zone_temp"))
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from simulation.config import LOGS_DIR, ensure_pyenergyplus_on_path


# ── data classes ─────────────────────────────────────────────────────────

@dataclass
class VariableSpec:
    """Specification for an EnergyPlus output variable to read."""
    var_name: str        # e.g. "Zone Mean Air Temperature"
    key: str             # e.g. "Office Zone"
    handle: int = -1     # resolved at runtime


@dataclass
class ActuatorSpec:
    """Specification for an EnergyPlus actuator to control."""
    component_type: str  # e.g. "Schedule:Constant"
    control_type: str    # e.g. "Schedule Value"
    actuator_key: str    # e.g. "Cooling Setpoint Schedule"
    handle: int = -1     # resolved at runtime


# ── runtime class ────────────────────────────────────────────────────────

class EnergyPlusRuntime:
    """
    High-level wrapper around the EnergyPlus Python API.

    Provides:
    - ``register_variable(name, ...)``  → declares a variable to read
    - ``register_actuator(name, ...)``  → declares an actuator to write
    - ``read_variable(name)``           → latest value of a registered variable
    - ``set_actuator(name, value)``     → queue an actuator write
    - ``run(idf, epw, ...)``            → execute the simulation
    """

    def __init__(self) -> None:
        self._variables: dict[str, VariableSpec] = {}
        self._actuators: dict[str, ActuatorSpec] = {}

        # Active actuator values (persisted across timesteps): name → value
        self._actuator_values: dict[str, float] = {}

        # Latest variable values: name → value
        self._latest_values: dict[str, float] = {}

        # Full timeseries: name → list of (timestep_index, value)
        self._timeseries: dict[str, list[tuple[int, float]]] = {}

        # Optional timestep callback for dynamic control logic: fn(runtime, step)
        self.on_timestep: Callable[[EnergyPlusRuntime, int], None] | None = None

        # Lock for thread-safe access
        self._lock = threading.Lock()

        # Internal state
        self._handles_resolved = False
        self._timestep_count = 0
        self._api: Any = None     # EnergyPlusAPI instance
        self._state: Any = None   # API state handle

    # ── registration ─────────────────────────────────────────────────

    def register_variable(
        self,
        name: str,
        var_name: str,
        key: str,
    ) -> None:
        """
        Register an output variable to read during simulation.

        Parameters
        ----------
        name : friendly name used in read_variable()
        var_name : EnergyPlus variable name (e.g. "Zone Mean Air Temperature")
        key : EnergyPlus key (zone name, "Environment", etc.)
        """
        self._variables[name] = VariableSpec(var_name=var_name, key=key)
        self._timeseries[name] = []

    def register_actuator(
        self,
        name: str,
        component_type: str,
        control_type: str,
        actuator_key: str,
    ) -> None:
        """
        Register an actuator to write during simulation.

        Parameters
        ----------
        name : friendly name used in set_actuator()
        component_type : e.g. "Schedule:Constant"
        control_type : e.g. "Schedule Value"
        actuator_key : e.g. "Cooling Setpoint Schedule"
        """
        self._actuators[name] = ActuatorSpec(
            component_type=component_type,
            control_type=control_type,
            actuator_key=actuator_key,
        )

    # ── read / write ─────────────────────────────────────────────────

    def read_variable(self, name: str) -> float:
        """
        Read the latest value of a registered variable.

        Thread-safe. Returns 0.0 if no value has been captured yet.
        """
        if name not in self._variables:
            raise KeyError(
                f"Variable '{name}' not registered. "
                f"Available: {list(self._variables.keys())}"
            )
        with self._lock:
            return self._latest_values.get(name, 0.0)

    def set_actuator(self, name: str, value: float) -> None:
        """
        Set an actuator value for the current and future timesteps.

        Thread-safe. The value will be applied at each timestep via
        ``begin_system_timestep_before_predictor`` callback.
        """
        if name not in self._actuators:
            raise KeyError(
                f"Actuator '{name}' not registered. "
                f"Available: {list(self._actuators.keys())}"
            )
        with self._lock:
            self._actuator_values[name] = float(value)

    def get_timeseries(self, name: str) -> list[tuple[int, float]]:
        """Return the full captured timeseries for a variable."""
        return list(self._timeseries.get(name, []))

    # ── simulation execution ─────────────────────────────────────────

    def run(
        self,
        idf_path: str | Path,
        epw_path: str | Path,
        output_dir: str | Path | None = None,
    ) -> dict:
        """
        Execute the EnergyPlus simulation with registered variables and actuators.

        Returns dict with exit_code, duration_s, output_files, etc.
        """
        ensure_pyenergyplus_on_path()
        from pyenergyplus.api import EnergyPlusAPI  # type: ignore[import-untyped]

        idf_path = Path(idf_path).resolve()
        epw_path = Path(epw_path).resolve()
        output_dir = Path(output_dir) if output_dir else LOGS_DIR
        output_dir.mkdir(parents=True, exist_ok=True)

        self._api = EnergyPlusAPI()
        self._state = self._api.state_manager.new_state()
        self._handles_resolved = False
        self._timestep_count = 0

        # Capture stdout messages
        stdout_log = output_dir / "energyplus_stdout.log"
        log_fh = open(stdout_log, "wb")

        def _msg_cb(msg) -> None:
            if isinstance(msg, str):
                msg = msg.encode("utf-8")
            log_fh.write(msg)
            log_fh.flush()

        self._api.runtime.callback_message(self._state, _msg_cb)

        # Register the main callback
        self._api.runtime.callback_begin_system_timestep_before_predictor(
            self._state, self._timestep_callback
        )

        # Build CLI args
        run_args = [
            "-w", str(epw_path),
            "-d", str(output_dir),
            "-r",
            str(idf_path),
        ]

        from datetime import datetime
        t0 = datetime.now()
        exit_code = self._api.runtime.run_energyplus(self._state, run_args)
        duration = (datetime.now() - t0).total_seconds()

        log_fh.close()

        # Gather output files
        output_files = [
            str(f) for f in sorted(output_dir.iterdir())
            if f.is_file()
        ]

        # Clean up API state
        self._api.state_manager.delete_state(self._state)

        return {
            "exit_code": exit_code,
            "duration_s": round(duration, 2),
            "timesteps_executed": self._timestep_count,
            "output_files": output_files,
        }

    # ── internal callback ────────────────────────────────────────────

    def _timestep_callback(self, state: Any) -> None:
        """Called at every simulation timestep by EnergyPlus."""
        api = self._api
        exchange = api.exchange

        # Skip warmup
        if exchange.warmup_flag(state):
            return

        # Resolve handles on first real timestep
        if not self._handles_resolved:
            self._resolve_handles(state)
            self._handles_resolved = True

        self._timestep_count += 1

        # ── User dynamic timestep callback (if registered) ──
        if self.on_timestep is not None:
            self.on_timestep(self, self._timestep_count)

        # ── Apply active actuator writes ──
        with self._lock:
            actuator_writes = dict(self._actuator_values)

        for name, value in actuator_writes.items():
            spec = self._actuators.get(name)
            if spec and spec.handle >= 0:
                exchange.set_actuator_value(state, spec.handle, value)

        # ── Read all registered variables ──
        for name, spec in self._variables.items():
            if spec.handle >= 0:
                val = exchange.get_variable_value(state, spec.handle)
                with self._lock:
                    self._latest_values[name] = val
                self._timeseries[name].append((self._timestep_count, val))

    def _resolve_handles(self, state: Any) -> None:
        """Resolve variable and actuator handles (called once)."""
        exchange = self._api.exchange

        for name, spec in self._variables.items():
            h = exchange.get_variable_handle(state, spec.var_name, spec.key)
            if h < 0:
                print(
                    f"[WARN] Could not resolve variable handle for "
                    f"'{name}' ({spec.var_name}, {spec.key})"
                )
            spec.handle = h

        for name, spec in self._actuators.items():
            h = exchange.get_actuator_handle(
                state,
                spec.component_type,
                spec.control_type,
                spec.actuator_key,
            )
            if h < 0:
                print(
                    f"[WARN] Could not resolve actuator handle for "
                    f"'{name}' ({spec.component_type}, {spec.control_type}, "
                    f"{spec.actuator_key})"
                )
            spec.handle = h
