"""
control/actions.py — Allowed Action Catalog.

Defines the fixed set of permitted control actions with min/max bounds.
Each action specifies which actuator it targets, the delta or absolute value,
and the hard limits that the resulting setpoint must stay within.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ActionType(Enum):
    """The type of control action."""
    ADJUST_HEATING_SETPOINT = "adjust_heating_setpoint"
    ADJUST_COOLING_SETPOINT = "adjust_cooling_setpoint"
    UNOCCUPIED_SETBACK = "unoccupied_setback"


@dataclass(frozen=True)
class ActionSpec:
    """Specification for a single permitted control action."""
    action_type: ActionType
    actuator_name: str          # Must match a registered actuator in EnergyPlusRuntime
    min_value: float            # Hard minimum for the resulting setpoint (°C)
    max_value: float            # Hard maximum for the resulting setpoint (°C)
    max_delta: float            # Maximum single-step change (°C)
    min_delta: float            # Minimum change to bother applying (deadband threshold)
    cooldown_steps: int         # Minimum timesteps between successive changes
    unit: str = "°C"


# ── The Catalog ──────────────────────────────────────────────────────────

ACTION_CATALOG: dict[ActionType, ActionSpec] = {
    ActionType.ADJUST_HEATING_SETPOINT: ActionSpec(
        action_type=ActionType.ADJUST_HEATING_SETPOINT,
        actuator_name="heating_setpoint_actuator",
        min_value=16.0,         # Never heat below 16 °C
        max_value=24.0,         # Never heat above 24 °C (must stay below cooling SP)
        max_delta=2.0,          # Max ±2 °C per step
        min_delta=0.25,         # Ignore changes < 0.25 °C
        cooldown_steps=4,       # 4 timesteps (~1 hour at 15-min intervals)
    ),
    ActionType.ADJUST_COOLING_SETPOINT: ActionSpec(
        action_type=ActionType.ADJUST_COOLING_SETPOINT,
        actuator_name="cooling_setpoint_actuator",
        min_value=22.0,         # Never cool below 22 °C (must stay above heating SP)
        max_value=30.0,         # Never cool above 30 °C
        max_delta=2.0,          # Max ±2 °C per step
        min_delta=0.25,         # Ignore changes < 0.25 °C
        cooldown_steps=4,       # 4 timesteps (~1 hour at 15-min intervals)
    ),
    ActionType.UNOCCUPIED_SETBACK: ActionSpec(
        action_type=ActionType.UNOCCUPIED_SETBACK,
        actuator_name="combined_setback", # Pseudo-actuator for state tracking
        min_value=0.0,          # The target_value is a relative drift (e.g. 2.0)
        max_value=2.0,          # Max drift per step is 2.0°C
        max_delta=2.0,          # (Same as max drift)
        min_delta=0.25,
        cooldown_steps=4,
    ),
}


@dataclass
class ControlAction:
    """A concrete action proposed by an agent or test harness."""
    action_type: ActionType
    target_value: float         # The desired new setpoint value (absolute, °C)
    reason: str = ""            # Optional: why this action is being proposed
