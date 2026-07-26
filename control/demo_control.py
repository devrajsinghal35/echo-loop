#!/usr/bin/env python3
"""
control/demo_control.py — Standalone verification script for the Control Core.

Verifies that the Control Core properly filters actions based on constraints,
deadbands, and cooldowns during a live simulation.
"""

import sys
from pathlib import Path

# Ensure the project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulation.config import EPW_PATH, IDF_PATH, LOGS_DIR
from simulation.runtime_wrapper import EnergyPlusRuntime

from telemetry.bus import default_bus
from telemetry.storage import TelemetryStorage
from telemetry.collector import TelemetryCollector
from telemetry.models import TelemetrySnapshot

from control.actions import ActionType, ControlAction
from control.core import ControlCore


def main() -> int:
    print("=" * 65)
    print("  Deterministic Control Core Verification")
    print("=" * 65)

    # 1. Setup Simulation & Telemetry
    rt = EnergyPlusRuntime()
    rt.register_variable("zone_temp", "Zone Mean Air Temperature", "Office Zone")
    rt.register_variable("heating_rate", "Zone Ideal Loads Supply Air Total Heating Rate", "OFFICE IDEAL LOADS")
    rt.register_variable("cooling_rate", "Zone Ideal Loads Supply Air Total Cooling Rate", "OFFICE IDEAL LOADS")
    rt.register_variable("iaq_co2", "Zone Air CO2 Concentration", "Office Zone")
    rt.register_variable("comfort_pmv", "Zone Thermal Comfort Fanger Model PMV", "Office People")
    
    rt.register_actuator("heating_setpoint_actuator", "Schedule:Constant", "Schedule Value", "Heating Setpoint Schedule")
    rt.register_actuator("cooling_setpoint_actuator", "Schedule:Constant", "Schedule Value", "Cooling Setpoint Schedule")

    # Track setpoints for our control logic
    rt.register_variable("heating_sp", "Schedule Value", "Heating Setpoint Schedule")
    rt.register_variable("cooling_sp", "Schedule Value", "Cooling Setpoint Schedule")

    collector = TelemetryCollector(rt, default_bus)
    core = ControlCore(rt)

    # Hardcoded test harness
    def test_harness(rt: EnergyPlusRuntime, step: int):
        # Read current state safely
        def safe_read(v):
            try: return rt.read_variable(v)
            except KeyError: return 0.0

        zone_temp = safe_read("zone_temp")
        pmv = safe_read("comfort_pmv")
        co2 = safe_read("iaq_co2")
        heat_sp = safe_read("heating_sp")
        cool_sp = safe_read("cooling_sp")

        # Propose actions at specific timesteps to test rules
        if step == 20:
            print(f"\n[Step 20] Telemetry BEFORE action: Cooling SP = {cool_sp:.2f}°C, Zone Temp = {zone_temp:.2f}°C")
            print(" -> Test 1: Valid Action (Drop cooling setpoint by 1.0°C)")
            action = ControlAction(ActionType.ADJUST_COOLING_SETPOINT, cool_sp - 1.0, "Valid step")
            resp = core.propose_action(action, step, zone_temp, pmv, co2, heat_sp, cool_sp)
            print(f" -> Result: {resp['approved']} - {resp['reason']}")

        elif step == 21:
            print("\n[Step 21] Test 2: Rapid Conflicting Action (Try to raise cooling setpoint immediately)")
            action = ControlAction(ActionType.ADJUST_COOLING_SETPOINT, cool_sp + 1.0, "Conflicting step")
            resp = core.propose_action(action, step, zone_temp, pmv, co2, heat_sp, cool_sp)
            print(f" -> Result: {resp['approved']} - {resp['reason']}")

        elif step == 22:
            print(f"\n[Step 22] Telemetry AFTER action: Cooling SP = {cool_sp:.2f}°C (Proof it changed!)")

        elif step == 30:
            print("\n[Step 30] Test 3: Deliberately Bad Action (Push setpoint to 35°C, outside hard bounds)")
            action = ControlAction(ActionType.ADJUST_COOLING_SETPOINT, 35.0, "Bad action")
            resp = core.propose_action(action, step, zone_temp, pmv, co2, heat_sp, cool_sp)
            print(f" -> Result: {resp['approved']} - {resp['reason']}")

        elif step == 120:
            print(f"\n[Step 120] Telemetry BEFORE action: PMV = {pmv:.2f} (Too Cold!), Zone Temp = {zone_temp:.2f}°C")
            print(" -> Test 4: PMV Constraint Violation (Try to drop heating setpoint when it's already too cold)")
            action = ControlAction(ActionType.ADJUST_HEATING_SETPOINT, heat_sp - 1.0, "Make colder")
            resp = core.propose_action(action, step, zone_temp, pmv, co2, heat_sp, cool_sp)
            print(f" -> Result: {resp['approved']} - {resp['reason']}")

            print("\n -> Test 5: Directional Recovery (Try to raise cooling setpoint to fix the cold PMV)")
            # Raise cooling setpoint to allow the room to warm up without hitting the 2.0 gap rule
            action2 = ControlAction(ActionType.ADJUST_COOLING_SETPOINT, cool_sp + 1.0, "Make warmer (Corrective)")
            resp2 = core.propose_action(action2, step, zone_temp, pmv, co2, heat_sp, cool_sp)
            print(f" -> Result: {resp2['approved']} - {resp2['reason']}")

    existing_collector_hook = rt.on_timestep
    
    def combined_hook(rt, step):
        if existing_collector_hook:
            existing_collector_hook(rt, step)
        if step > 1: # Skip uninitialized warmup step
            test_harness(rt, step)

    rt.on_timestep = combined_hook

    # 4. Run Simulation
    print(f"\n🚀 Running EnergyPlus with Control Core Hardcoded Tests...")
    result = rt.run(
        idf_path=str(IDF_PATH),
        epw_path=str(EPW_PATH),
        output_dir=str(LOGS_DIR),
    )

    if result["exit_code"] != 0:
        print("❌ Simulation failed!")
        return 1
        
    print("\n✅ Verification complete. Check the output above to ensure constraints worked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
