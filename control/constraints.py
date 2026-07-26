"""
control/constraints.py — Thermal Comfort and Air Quality Safety Bounds.

Core environmental limits that must never be violated. Checked against 
telemetry snapshots before applying any HVAC setpoint adjustments.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ComfortConstraints:
    """Safety and comfort margins enforced in the office space."""
    # Temperature thresholds (°C)
    temp_min: float = 20.0
    temp_max: float = 26.0

    # Predicted Mean Vote (PMV) boundaries
    pmv_min: float = -0.5
    pmv_max: float = 0.5

    # Carbon Dioxide concentration limit (ppm)
    co2_max: float = 1000.0     # Under ASHRAE 62.1 standards

    # Required deadband separation between heating and cooling setpoints
    min_setpoint_gap: float = 2.0   # Heating setpoint must stay 2°C below cooling setpoint


# Standard operating limits
DEFAULT_CONSTRAINTS = ComfortConstraints()


def check_temperature_bounds(
    zone_temp: float,
    constraints: ComfortConstraints = DEFAULT_CONSTRAINTS,
) -> tuple[bool, str]:
    """Check if current zone temperature is within safety bounds."""
    if zone_temp < constraints.temp_min:
        return False, f"Zone temp {zone_temp:.1f}°C below minimum {constraints.temp_min}°C"
    if zone_temp > constraints.temp_max:
        return False, f"Zone temp {zone_temp:.1f}°C above maximum {constraints.temp_max}°C"
    return True, "Temperature within bounds"


def check_pmv_bounds(
    pmv: float,
    constraints: ComfortConstraints = DEFAULT_CONSTRAINTS,
) -> tuple[bool, str]:
    """Check if current PMV is within comfort bounds."""
    if pmv < constraints.pmv_min:
        return False, f"PMV {pmv:.2f} below minimum {constraints.pmv_min} (too cold)"
    if pmv > constraints.pmv_max:
        return False, f"PMV {pmv:.2f} above maximum {constraints.pmv_max} (too warm)"
    return True, "PMV within comfort bounds"


def check_co2_bounds(
    co2_ppm: float,
    constraints: ComfortConstraints = DEFAULT_CONSTRAINTS,
) -> tuple[bool, str]:
    """Check if current CO2 concentration is below the safety limit."""
    if co2_ppm > constraints.co2_max:
        return False, f"CO2 {co2_ppm:.0f} ppm exceeds limit {constraints.co2_max:.0f} ppm"
    return True, "CO2 within bounds"


def check_setpoint_gap(
    heating_sp: float,
    cooling_sp: float,
    constraints: ComfortConstraints = DEFAULT_CONSTRAINTS,
) -> tuple[bool, str]:
    """Ensure heating setpoint is sufficiently below cooling setpoint."""
    gap = cooling_sp - heating_sp
    if gap < constraints.min_setpoint_gap:
        return False, (
            f"Setpoint gap {gap:.1f}°C is below minimum {constraints.min_setpoint_gap}°C "
            f"(heating={heating_sp:.1f}, cooling={cooling_sp:.1f})"
        )
    return True, f"Setpoint gap {gap:.1f}°C OK"
