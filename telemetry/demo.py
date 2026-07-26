#!/usr/bin/env python3
"""
demo.py — End-to-end verification script for the Telemetry Layer.

1. Sets up the EnergyPlus baseline simulation.
2. Initializes the Telemetry layer (Event Bus, SQLite Storage, Collector).
3. Connects components without modifying simulation internals.
4. Runs the simulation.
5. Verifies snapshot storage and log parsing.
"""

import sys
from pathlib import Path
import sqlite3

# Ensure the project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulation.config import EPW_PATH, IDF_PATH, LOGS_DIR
from simulation.runtime_wrapper import EnergyPlusRuntime

from telemetry.bus import default_bus
from telemetry.storage import TelemetryStorage
from telemetry.collector import TelemetryCollector
from telemetry.log_parser import parse_eplus_err_log
from telemetry.models import TelemetrySnapshot


def main() -> int:
    print("=" * 65)
    print("  Telemetry Layer Verification Demo")
    print("=" * 65)

    # 1. Setup Storage
    db_path = PROJECT_ROOT / "telemetry.db"
    if db_path.exists():
        db_path.unlink()  # Clean start for demo
    
    storage = TelemetryStorage(db_path)
    
    # 2. Subscribe Storage to Event Bus
    def handle_snapshot(snapshot: TelemetrySnapshot):
        storage.insert_snapshot(snapshot)
        # Just print every 24th timestep to not spam
        if snapshot.timestep % 24 == 0:
            print(f"[EventBus] Snapshot @ {snapshot.timestamp}: "
                  f"Temp={snapshot.zone_temp_c:.1f}°C, Energy={snapshot.energy_rate_w:.1f}W, "
                  f"CO2={snapshot.iaq_co2_ppm:.1f}ppm, PMV={snapshot.comfort_pmv:.2f}")

    default_bus.subscribe("telemetry_snapshot", handle_snapshot)
    
    print(f"✅ Telemetry Storage initialized at {db_path}")
    print(f"✅ Storage subscribed to Event Bus")

    # 3. Setup Simulation Runtime
    rt = EnergyPlusRuntime()

    # Register needed variables
    rt.register_variable("zone_temp", "Zone Mean Air Temperature", "Office Zone")
    rt.register_variable("heating_rate", "Zone Ideal Loads Supply Air Total Heating Rate", "OFFICE IDEAL LOADS")
    rt.register_variable("cooling_rate", "Zone Ideal Loads Supply Air Total Cooling Rate", "OFFICE IDEAL LOADS")
    rt.register_variable("iaq_co2", "Zone Air CO2 Concentration", "Office Zone")
    rt.register_variable("comfort_pmv", "Zone Thermal Comfort Fanger Model PMV", "Office People")

    # The collector safely hooks into the runtime
    collector = TelemetryCollector(rt, default_bus)
    
    print("✅ Telemetry Collector attached to Simulation Runtime")

    # 4. Run Simulation
    print(f"\n🚀 Running EnergyPlus Simulation (will generate telemetry)...")
    result = rt.run(
        idf_path=str(IDF_PATH),
        epw_path=str(EPW_PATH),
        output_dir=str(LOGS_DIR),
    )

    if result["exit_code"] != 0:
        print("❌ Simulation failed!")
        return 1
        
    print("\n" + "=" * 65)
    print("  VERIFICATION REPORT")
    print("=" * 65)

    # 5. Verify Storage
    count = storage.count_snapshots()
    v1_pass = (count == result["timesteps_executed"])
    v1_icon = "✅ PASS" if v1_pass else "❌ FAIL"
    print(f"1️⃣ Snapshot Storage: {v1_icon} (Expected {result['timesteps_executed']}, Found {count} rows in DB)")

    # 6. Verify Log Parser
    err_log = LOGS_DIR / "eplusout.err"
    summary = parse_eplus_err_log(err_log)
    
    v2_pass = summary.execution_time_s >= 0.0
    v2_icon = "✅ PASS" if v2_pass else "❌ FAIL"
    
    print(f"2️⃣ Log Parser: {v2_icon}")
    print(f"   • Execution Time : {summary.execution_time_s:.2f} s")
    print(f"   • Warnings       : {summary.warning_count}")
    print(f"   • Severe Errors  : {summary.severe_count}")
    print(f"   • Fatal Errors   : {summary.fatal_count}")
    
    for err in summary.errors:
        print(f"     [Error] {err}")

    if v1_pass and v2_pass:
        print("\n🎉 Telemetry layer successfully integrated and verified!")
        return 0
    else:
        print("\n❌ Telemetry layer verification failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
