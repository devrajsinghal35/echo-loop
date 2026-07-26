from simulation.runtime_wrapper import EnergyPlusRuntime
from telemetry.models import TelemetrySnapshot
from telemetry.bus import default_bus

class TelemetryCollector:
    """Passively reads from the simulation runner and normalizes into TelemetrySnapshots."""
    
    def __init__(self, runtime: EnergyPlusRuntime, bus=default_bus):
        self.runtime = runtime
        self.bus = bus
        self._setup_hook()

    def _setup_hook(self):
        """Chain into the runtime's on_timestep callback."""
        existing_callback = self.runtime.on_timestep
        
        def _telemetry_hook(rt: EnergyPlusRuntime, step: int):
            # 1. Call existing callback if there is one (preserve existing logic)
            if existing_callback:
                existing_callback(rt, step)
                
            def safe_read(var_name: str) -> float:
                try:
                    return rt.read_variable(var_name)
                except KeyError:
                    return 0.0

            # 2. Collect and normalize telemetry
            zone_temp = safe_read("zone_temp")
            heating_rate = safe_read("heating_rate")
            cooling_rate = safe_read("cooling_rate")
            
            # Note: IAQ and PMV aren't calculated in the current baseline,
            # so they will safely return 0.0.
            iaq_co2 = safe_read("iaq_co2")
            comfort_pmv = safe_read("comfort_pmv")
            
            # Simple combined energy rate (W)
            energy_rate = heating_rate + cooling_rate
            
            # Create a simple timestamp for the snapshot
            timestamp = f"Day-Step {step}"
            
            snapshot = TelemetrySnapshot(
                timestep=step,
                timestamp=timestamp,
                is_warmup=(step == 1),
                zone_temp_c=zone_temp,
                energy_rate_w=energy_rate,
                iaq_co2_ppm=iaq_co2,
                comfort_pmv=comfort_pmv,
            )
            
            # 3. Publish to event bus
            self.bus.publish("telemetry_snapshot", snapshot)

        self.runtime.on_timestep = _telemetry_hook
