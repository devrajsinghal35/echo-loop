"""
control/core.py — Deterministic HVAC Safety Enforcement Core.

Defines the `ControlCore` engine with safety checks on recommended decisions.
Applies active safety guidelines, cooldown checks, and passes decisions to EnergyPlus.
"""

from __future__ import annotations

import threading
from typing import TypedDict

from control.actions import ACTION_CATALOG, ActionType, ControlAction
from control.constraints import (
    DEFAULT_CONSTRAINTS,
    check_pmv_bounds,
    check_setpoint_gap,
    check_temperature_bounds,
)
from simulation.runtime_wrapper import EnergyPlusRuntime


class ActionResponse(TypedDict):
    """Response returned when an action is proposed."""
    approved: bool
    reason: str
    executed: bool


class ControlCore:
    """
    Deterministic control core.
    
    Enforces rules, bounds, and state tracking across timesteps.
    """
    def __init__(self, runtime: EnergyPlusRuntime):
        self._runtime = runtime
        self._lock = threading.Lock()
        
        # State tracking for cooldown and deadbands
        # actuator_name -> (last_value, last_step)
        self._last_writes: dict[str, tuple[float, int]] = {}

    def propose_recommendation(
        self,
        recommendation: dict,
        current_step: int,
        current_zone_temp: float,
        current_pmv: float,
        current_co2_ppm: float,
        current_heating_sp: float,
        current_cooling_sp: float,
    ) -> ActionResponse:
        """
        Bridge an agent/MCP `recommend_action` output dict directly into `propose_action`.
        
        Translates raw dictionary recommendations into a validated ControlAction.
        """
        action_type_str = recommendation.get("action_type", "no_action")
        target_value = recommendation.get("target_value")
        rationale = recommendation.get("rationale", "")

        if action_type_str == "no_action" or target_value is None:
            return ActionResponse(
                approved=False,
                reason="Recommendation specified no_action or missing target_value.",
                executed=False,
            )

        try:
            action_type = ActionType(action_type_str)
        except ValueError:
            return ActionResponse(
                approved=False,
                reason=f"Invalid action_type in recommendation: {action_type_str}",
                executed=False,
            )

        action = ControlAction(
            action_type=action_type,
            target_value=float(target_value),
            reason=rationale,
        )

        return self.propose_action(
            action=action,
            current_step=current_step,
            current_zone_temp=current_zone_temp,
            current_pmv=current_pmv,
            current_co2_ppm=current_co2_ppm,
            current_heating_sp=current_heating_sp,
            current_cooling_sp=current_cooling_sp,
        )

    def propose_action(
        self,
        action: ControlAction,
        current_step: int,
        current_zone_temp: float,
        current_pmv: float,
        current_co2_ppm: float,
        current_heating_sp: float,
        current_cooling_sp: float,
    ) -> ActionResponse:
        """
        Propose a control action.
        Evaluates it against all deterministic rules and executes it if approved.
        """
        with self._lock:
            # 1. Look up action in catalog
            if action.action_type not in ACTION_CATALOG:
                return ActionResponse(
                    approved=False,
                    reason=f"Unknown action type: {action.action_type}",
                    executed=False,
                )
            spec = ACTION_CATALOG[action.action_type]

            # Special bypass for UNOCCUPIED_SETBACK
            if action.action_type == ActionType.UNOCCUPIED_SETBACK:
                # Explicitly set the unoccupied setback targets to 25.0 and 20.0
                # This guarantees they are within 2.0°C of the baseline (23.0/22.0)
                # so the morning recovery can happen in a single step.
                proposed_cooling = 25.0
                proposed_heating = 20.0
                
                gap_ok, gap_reason = check_setpoint_gap(proposed_heating, proposed_cooling)
                if not gap_ok:
                    return ActionResponse(approved=False, reason=gap_reason, executed=False)
                
                # Check Cooldown
                last_step = 0
                if "cooling_setpoint_actuator" in self._last_writes:
                    _, last_step = self._last_writes["cooling_setpoint_actuator"]
                
                steps_since = current_step - last_step
                if steps_since < spec.cooldown_steps and last_step != 0:
                    return ActionResponse(
                        approved=False,
                        reason=f"In cooldown: {steps_since}/{spec.cooldown_steps} steps since last change.",
                        executed=False,
                    )

                self._runtime.set_actuator("cooling_setpoint_actuator", proposed_cooling)
                self._runtime.set_actuator("heating_setpoint_actuator", proposed_heating)
                self._last_writes["cooling_setpoint_actuator"] = (proposed_cooling, current_step)
                self._last_writes["heating_setpoint_actuator"] = (proposed_heating, current_step)
                
                return ActionResponse(
                    approved=True,
                    reason=f"Unoccupied setback applied: cooling to {proposed_cooling:.2f}, heating to {proposed_heating:.2f}.",
                    executed=True,
                )

            # 2. Check Action Bounds (min/max)
            if action.target_value < spec.min_value or action.target_value > spec.max_value:
                return ActionResponse(
                    approved=False,
                    reason=f"Target {action.target_value:.2f} violates hard bounds [{spec.min_value}, {spec.max_value}]",
                    executed=False,
                )

            # Determine proposed setpoints for gap check
            proposed_heating_sp = current_heating_sp
            proposed_cooling_sp = current_cooling_sp
            current_sp = current_heating_sp
            
            if spec.action_type == ActionType.ADJUST_HEATING_SETPOINT:
                proposed_heating_sp = action.target_value
                current_sp = current_heating_sp
            elif spec.action_type == ActionType.ADJUST_COOLING_SETPOINT:
                proposed_cooling_sp = action.target_value
                current_sp = current_cooling_sp

            # 3. Check Safety and Comfort Constraints
            # Setpoint Gap Rule (Fatal if violated)
            gap_ok, gap_reason = check_setpoint_gap(proposed_heating_sp, proposed_cooling_sp)
            if not gap_ok:
                return ActionResponse(approved=False, reason=gap_reason, executed=False)

            # Directional Recovery Logic:
            # If PMV or Temp are out of bounds, we only reject actions that make it worse.
            # e.g., if PMV is too hot (> 0.5), we reject raising the setpoint further.
            
            # PMV
            if current_pmv > DEFAULT_CONSTRAINTS.pmv_max and action.target_value > current_sp:
                return ActionResponse(
                    approved=False, 
                    reason=f"Rejected: PMV ({current_pmv:.2f}) is too hot. Cannot raise setpoint.", 
                    executed=False
                )
            if current_pmv < DEFAULT_CONSTRAINTS.pmv_min and action.target_value < current_sp:
                return ActionResponse(
                    approved=False, 
                    reason=f"Rejected: PMV ({current_pmv:.2f}) is too cold. Cannot lower setpoint.", 
                    executed=False
                )

            # Temp
            if current_zone_temp > DEFAULT_CONSTRAINTS.temp_max and action.target_value > current_sp:
                return ActionResponse(
                    approved=False, 
                    reason=f"Rejected: Temp ({current_zone_temp:.1f}°C) is too hot. Cannot raise setpoint.", 
                    executed=False
                )
            if current_zone_temp < DEFAULT_CONSTRAINTS.temp_min and action.target_value < current_sp:
                return ActionResponse(
                    approved=False, 
                    reason=f"Rejected: Temp ({current_zone_temp:.1f}°C) is too cold. Cannot lower setpoint.", 
                    executed=False
                )

            # 4. Check Deadband (min_delta)
            delta = abs(action.target_value - current_sp)
            if delta < spec.min_delta:
                return ActionResponse(
                    approved=False,
                    reason=f"Change {delta:.2f} is below minimum threshold (deadband) of {spec.min_delta}",
                    executed=False,
                )

            # 5. Check Max Delta
            if delta > spec.max_delta:
                return ActionResponse(
                    approved=False,
                    reason=f"Change {delta:.2f} exceeds maximum allowed step of {spec.max_delta}",
                    executed=False,
                )

            # 6. Check Cooldown
            if spec.actuator_name in self._last_writes:
                _, last_step = self._last_writes[spec.actuator_name]
                steps_since = current_step - last_step
                if steps_since < spec.cooldown_steps:
                    return ActionResponse(
                        approved=False,
                        reason=f"In cooldown: {steps_since}/{spec.cooldown_steps} steps since last change.",
                        executed=False,
                    )

            # Passed all checks! Execute.
            self._runtime.set_actuator(spec.actuator_name, action.target_value)
            self._last_writes[spec.actuator_name] = (action.target_value, current_step)

            return ActionResponse(
                approved=True,
                reason="Action approved and executed.",
                executed=True,
            )
