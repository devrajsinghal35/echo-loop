#!/usr/bin/env python3
"""
control/test_recommendation_bridge.py — Verification of agent recommendation integration.

Tests wiring recommend_action() output dicts directly into control.propose_action()
via ControlCore.propose_recommendation().

Confirms that:
  1. Valid recommendations pass and execute.
  2. Deliberately wrong / harmful recommendations (e.g. cooling setpoint drop when cold,
     out-of-bounds targets, invalid action types) are strictly REJECTED and logged.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulation.config import EPW_PATH, IDF_PATH, LOGS_DIR
from simulation.runtime_wrapper import EnergyPlusRuntime
from control.core import ControlCore
from agent.mcp_server.server import recommend_action


def run_bridge_tests():
    print("=" * 65)
    print("  Agent Recommendation → Control Core Integration Test")
    print("=" * 65)

    rt = EnergyPlusRuntime()
    rt.register_variable("zone_temp", "Zone Mean Air Temperature", "Office Zone")
    rt.register_variable("heating_rate", "Zone Ideal Loads Supply Air Total Heating Rate", "OFFICE IDEAL LOADS")
    rt.register_variable("cooling_rate", "Zone Ideal Loads Supply Air Total Cooling Rate", "OFFICE IDEAL LOADS")
    rt.register_variable("iaq_co2", "Zone Air CO2 Concentration", "Office Zone")
    rt.register_variable("comfort_pmv", "Zone Thermal Comfort Fanger Model PMV", "Office People")

    rt.register_actuator("heating_setpoint_actuator", "Schedule:Constant", "Schedule Value", "Heating Setpoint Schedule")
    rt.register_actuator("cooling_setpoint_actuator", "Schedule:Constant", "Schedule Value", "Cooling Setpoint Schedule")

    rt.register_variable("heating_sp", "Schedule Value", "Heating Setpoint Schedule")
    rt.register_variable("cooling_sp", "Schedule Value", "Cooling Setpoint Schedule")

    core = ControlCore(rt)
    test_results = []

    def simulation_harness(rt: EnergyPlusRuntime, step: int):
        def safe_read(v):
            try: return rt.read_variable(v)
            except KeyError: return 0.0

        zone_temp = safe_read("zone_temp")
        pmv = safe_read("comfort_pmv")
        co2 = safe_read("iaq_co2")
        heat_sp = safe_read("heating_sp")
        cool_sp = safe_read("cooling_sp")

        # Test Case 1: Real recommend_action() call wired directly into propose_recommendation
        if step == 20:
            print(f"\n[Step 20] Live state: Temp={zone_temp:.1f}°C, PMV={pmv:.2f}, HeatSP={heat_sp:.1f}°C, CoolSP={cool_sp:.1f}°C")
            rec = recommend_action(target="balanced", constraint_mode="strict")
            print(f" -> Live recommend_action() output: {rec}")
            
            resp = core.propose_recommendation(
                recommendation=rec,
                current_step=step,
                current_zone_temp=zone_temp,
                current_pmv=pmv,
                current_co2_ppm=co2,
                current_heating_sp=heat_sp,
                current_cooling_sp=cool_sp,
            )
            print(f" -> Control Core result: approved={resp['approved']}, reason={resp['reason']!r}")
            test_results.append(("Test 1 (Live Valid Recommendation)", resp['approved'] == True))

        # Test Case 2: Deliberately harmful LLM recommendation (cooling setpoint drop when room is cold, PMV = -0.94)
        elif step == 120:
            print(f"\n[Step 120] Live state: Temp={zone_temp:.1f}°C, PMV={pmv:.2f} (COLD!)")
            harmful_rec = {
                "action_type": "adjust_cooling_setpoint",
                "target_value": 23.8,  # Lower cooling SP from 24 to 23.8 (passes gap gap 23.8-21.5=2.3 >= 2.0)
                "confidence": 0.9,
                "rationale": "Erroneous LLM: lower cooling setpoint when room is already too cold",
                "schema_version": "1.0",
            }
            print(f" -> Simulating Harmful LLM Recommendation: {harmful_rec}")
            
            resp = core.propose_recommendation(
                recommendation=harmful_rec,
                current_step=step,
                current_zone_temp=zone_temp,
                current_pmv=pmv,
                current_co2_ppm=co2,
                current_heating_sp=heat_sp,
                current_cooling_sp=cool_sp,
            )
            print(f" -> Control Core result: approved={resp['approved']}, reason={resp['reason']!r}")
            # MUST be rejected on PMV grounds
            is_rejected = (resp['approved'] == False and "PMV" in resp['reason'])
            test_results.append(("Test 2 (Harmful LLM Rejection on PMV Grounds)", is_rejected))

        # Test Case 3: Deliberately out-of-bounds LLM recommendation (target = 35°C)
        elif step == 130:
            out_of_bounds_rec = {
                "action_type": "adjust_cooling_setpoint",
                "target_value": 35.0,
                "confidence": 0.95,
                "rationale": "Erroneous LLM: target 35°C exceeds maximum cooling bound 30°C",
                "schema_version": "1.0",
            }
            print(f"\n[Step 130] Simulating Out-of-Bounds LLM Recommendation: {out_of_bounds_rec}")
            resp = core.propose_recommendation(
                recommendation=out_of_bounds_rec,
                current_step=step,
                current_zone_temp=zone_temp,
                current_pmv=pmv,
                current_co2_ppm=co2,
                current_heating_sp=heat_sp,
                current_cooling_sp=cool_sp,
            )
            print(f" -> Control Core result: approved={resp['approved']}, reason={resp['reason']!r}")
            # MUST be rejected on hard bounds
            is_rejected = (resp['approved'] == False and "hard bounds" in resp['reason'])
            test_results.append(("Test 3 (Out-of-Bounds LLM Rejection)", is_rejected))

        # Test Case 4: Deliberately harmful LLM recommendation (heating setpoint raise when room is hot, PMV = +1.0)
        # We simulate a hot state for step 140 (even if not naturally occurring in winter design day, we override the inputs)
        elif step == 140:
            simulated_pmv_hot = 0.95
            print(f"\n[Step 140] Simulated Live state: Temp=26.0°C, PMV={simulated_pmv_hot:.2f} (HOT!)")
            harmful_rec_hot = {
                "action_type": "adjust_heating_setpoint",
                "target_value": 22.0,  # Raise heating SP from 21.0 to 22.0 (gap check passes with cooling at 24.0)
                "confidence": 0.85,
                "rationale": "Erroneous LLM: raise heating setpoint when room is already too hot",
                "schema_version": "1.0",
            }
            print(f" -> Simulating Harmful LLM Recommendation: {harmful_rec_hot}")
            
            resp = core.propose_recommendation(
                recommendation=harmful_rec_hot,
                current_step=step,
                current_zone_temp=26.0,
                current_pmv=simulated_pmv_hot,
                current_co2_ppm=co2,
                current_heating_sp=21.0,
                current_cooling_sp=24.0,
            )
            print(f" -> Control Core result: approved={resp['approved']}, reason={resp['reason']!r}")
            # MUST be rejected on PMV grounds
            is_rejected = (resp['approved'] == False and "PMV" in resp['reason'] and "too hot" in resp['reason'])
            test_results.append(("Test 4 (Harmful LLM Rejection on PMV Hot Grounds)", is_rejected))

    def combined_hook(rt, step):
        if step > 1:
            simulation_harness(rt, step)

    rt.on_timestep = combined_hook

    print("\n🚀 Running simulation with recommend_action() → Control Core bridge tests...")
    result = rt.run(
        idf_path=str(IDF_PATH),
        epw_path=str(EPW_PATH),
        output_dir=str(LOGS_DIR),
    )

    if result["exit_code"] != 0:
        print("❌ Simulation failed!")
        return 1

    print("\n" + "=" * 65)
    print("  VERIFICATION SUMMARY")
    print("=" * 65)
    all_passed = True
    for name, passed in test_results:
        icon = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {icon} — {name}")
        if not passed:
            all_passed = False

    if all_passed:
        print("\n🎉 ALL BRIDGE INTEGRATION TESTS PASSED — Control Core successfully guards against bad LLM outputs.")
        return 0
    else:
        print("\n❌ SOME TESTS FAILED.")
        return 1


if __name__ == "__main__":
    sys.exit(run_bridge_tests())
