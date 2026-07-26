#!/usr/bin/env python3
"""
run_baseline.py — Execute the baseline EnergyPlus simulation end-to-end with strict verification.

Verification Steps:
  1. Exit code is 0 (successful completion).
  2. CSV/ESO outputs contain real numeric data (temps, energy).
  3. read_variable() returns live simulation values at each timestep.
  4. set_actuator() demonstrably alters downstream simulation state (e.g. setpoint step change
     causes zone temp and HVAC heating rate to shift).

Run:
    cd /Users/devrajsinghal/honeywell
    ENERGYPLUS_DIR=$HOME/EnergyPlus-24-2-0 python3 -m simulation.run_baseline
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

# Ensure the project root is on sys.path so `simulation` is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulation.config import (
    EPW_PATH,
    IDF_PATH,
    LOGS_DIR,
    print_status,
    validate_all,
)
from simulation.runtime_wrapper import EnergyPlusRuntime


def main() -> int:
    print("=" * 65)
    print("  EnergyPlus Baseline Simulation & Actuator Verification Runner")
    print("=" * 65)

    # ── 1. Validate ──────────────────────────────────────────────
    print_status()
    checks = validate_all()
    failures = [k for k, v in checks.items() if not v]
    if failures:
        print(f"\n❌ Pre-flight checks failed: {failures}")
        return 1

    # ── 2. Prepare output directory ──────────────────────────────
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"📁 Output directory: {LOGS_DIR}")

    # ── 3. Initialise runtime wrapper ────────────────────────────
    rt = EnergyPlusRuntime()

    # Register variables to read
    rt.register_variable(
        "zone_temp",
        "Zone Mean Air Temperature",
        "Office Zone",
    )
    rt.register_variable(
        "outdoor_temp",
        "Site Outdoor Air Drybulb Temperature",
        "Environment",
    )
    rt.register_variable(
        "heating_rate",
        "Zone Ideal Loads Supply Air Total Heating Rate",
        "OFFICE IDEAL LOADS",
    )
    rt.register_variable(
        "cooling_rate",
        "Zone Ideal Loads Supply Air Total Cooling Rate",
        "OFFICE IDEAL LOADS",
    )
    rt.register_variable(
        "heating_setpoint",
        "Schedule Value",
        "Heating Setpoint Schedule",
    )

    # Register actuators to write
    rt.register_actuator(
        "heating_setpoint_actuator",
        "Schedule:Constant",
        "Schedule Value",
        "Heating Setpoint Schedule",
    )
    rt.register_actuator(
        "cooling_setpoint_actuator",
        "Schedule:Constant",
        "Schedule Value",
        "Cooling Setpoint Schedule",
    )

    # Define dynamic runtime control logic (step change at timestep 45)
    # Timesteps 1-44: Heating SP = 16.0 °C, Cooling SP = 24.0 °C
    # Timesteps 45+:  Heating SP = 22.0 °C, Cooling SP = 28.0 °C
    def dynamic_control(runtime: EnergyPlusRuntime, step: int) -> None:
        if step < 45:
            runtime.set_actuator("heating_setpoint_actuator", 16.0)
            runtime.set_actuator("cooling_setpoint_actuator", 24.0)
        else:
            runtime.set_actuator("heating_setpoint_actuator", 22.0)
            runtime.set_actuator("cooling_setpoint_actuator", 28.0)

    rt.on_timestep = dynamic_control

    print("\n📋 Registered variables:")
    for name in rt._variables:
        spec = rt._variables[name]
        print(f"   • {name}: {spec.var_name} [{spec.key}]")
    print("\n📋 Registered actuators:")
    for name in rt._actuators:
        spec = rt._actuators[name]
        print(f"   • {name}: {spec.component_type}/{spec.control_type} [{spec.actuator_key}]")

    # ── 4. Run simulation ────────────────────────────────────────
    print(f"\n🚀 Starting EnergyPlus simulation...")
    result = rt.run(
        idf_path=str(IDF_PATH),
        epw_path=str(EPW_PATH),
        output_dir=str(LOGS_DIR),
    )

    # ── 5. Verification 1: Run Completion & Exit Code ────────────
    print("\n" + "=" * 65)
    print("  VERIFICATION REPORT")
    print("=" * 65)

    exit_code = result["exit_code"]
    v1_pass = (exit_code == 0)
    v1_icon = "✅ PASS" if v1_pass else "❌ FAIL"
    print(f"\n1️⃣ Simulation Run Completion: {v1_icon} (Exit code: {exit_code}, Timesteps: {result['timesteps_executed']})")

    if not v1_pass:
        print("   Fatal error during EnergyPlus run!")
        return exit_code

    # ── 6. Verification 2: Output CSV/ESO Data Inspection ───────
    csv_file = LOGS_DIR / "eplusout.csv"
    v2_pass = False
    row_count = 0
    non_zero_temps = 0

    if csv_file.exists():
        with open(csv_file, "r") as f:
            reader = csv.reader(f)
            headers = next(reader, None)
            for row in reader:
                if row:
                    row_count += 1
                    try:
                        outdoor = float(row[1])
                        zone_t = float(row[2])
                        if abs(outdoor) > 0.1 and abs(zone_t) > 0.1:
                            non_zero_temps += 1
                    except (ValueError, IndexError):
                        pass

        if row_count > 0 and non_zero_temps > 0:
            v2_pass = True

    v2_icon = "✅ PASS" if v2_pass else "❌ FAIL"
    print(f"2️⃣ Output CSV/ESO Data Check : {v2_icon} ({row_count} rows in CSV, non-zero temp rows: {non_zero_temps})")

    # ── 7. Verification 3: Live read_variable() Data Check ────────
    ts_zone = rt.get_timeseries("zone_temp")
    v3_pass = len(ts_zone) > 0 and any(val != 0.0 for _, val in ts_zone)
    v3_icon = "✅ PASS" if v3_pass else "❌ FAIL"
    first_temp = ts_zone[0][1] if ts_zone else 0.0
    last_temp = ts_zone[-1][1] if ts_zone else 0.0
    print(f"3️⃣ Live read_variable() Check: {v3_icon} ({len(ts_zone)} samples captured, t1={first_temp:.2f}°C, t_end={last_temp:.2f}°C)")

    # ── 8. Verification 4: Downstream set_actuator() Impact Check ─
    ts_sp = rt.get_timeseries("heating_setpoint")
    ts_heat = rt.get_timeseries("heating_rate")
    ts_cool = rt.get_timeseries("cooling_rate")

    sp_before = [v for step, v in ts_sp if step < 45]
    sp_after = [v for step, v in ts_sp if step >= 45]
    
    # Analyze in period where heating/cooling is active
    heat_before = [v for step, v in ts_heat if step < 45]
    heat_after = [v for step, v in ts_heat if step >= 45]
    cool_before = [v for step, v in ts_cool if step < 45]
    cool_after = [v for step, v in ts_cool if step >= 45]

    avg_sp_before = sum(sp_before) / len(sp_before) if sp_before else 0
    avg_sp_after = sum(sp_after) / len(sp_after) if sp_after else 0
    avg_heat_before = sum(heat_before) / len(heat_before) if heat_before else 0
    avg_heat_after = sum(heat_after) / len(heat_after) if heat_after else 0
    avg_cool_before = sum(cool_before) / len(cool_before) if cool_before else 0
    avg_cool_after = sum(cool_after) / len(cool_after) if cool_after else 0

    sp_changed = abs(avg_sp_after - avg_sp_before) > 3.0
    energy_responded = (abs(avg_heat_after - avg_heat_before) > 50.0) or (abs(avg_cool_after - avg_cool_before) > 50.0)
    v4_pass = sp_changed and energy_responded
    v4_icon = "✅ PASS" if v4_pass else "❌ FAIL"

    print(f"4️⃣ Actuator Downstream Shift  : {v4_icon}")
    print(f"   • Setpoint before step (t<45) : {avg_sp_before:.1f} °C")
    print(f"   • Setpoint after step  (t>=45): {avg_sp_after:.1f} °C")
    print(f"   • Heating rate before step    : {avg_heat_before:.1f} W")
    print(f"   • Heating rate after step     : {avg_heat_after:.1f} W")
    print(f"   • Cooling rate before step    : {avg_cool_before:.1f} W")
    print(f"   • Cooling rate after step     : {avg_cool_after:.1f} W")

    all_passed = v1_pass and v2_pass and v3_pass and v4_pass

    print("\n" + "=" * 65)
    if all_passed:
        print(" 🎉 ALL 4 VERIFICATION CHECKS PASSED SUCCESSFULLY!")
        print("=" * 65 + "\n")
        return 0
    else:
        print(" ❌ VERIFICATION FAILED! Actuator or simulation layer issue.")
        print("=" * 65 + "\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
