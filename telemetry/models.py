from dataclasses import dataclass

@dataclass
class TelemetrySnapshot:
    """Structured state object for a single simulation timestep snapshot."""
    timestep: int
    timestamp: str  # ISO format string or just 'YYYY-MM-DD HH:MM:SS'
    is_warmup: bool
    zone_temp_c: float
    energy_rate_w: float
    iaq_co2_ppm: float
    comfort_pmv: float

@dataclass
class LogSummary:
    """Structured summary of an EnergyPlus run log."""
    execution_time_s: float
    warning_count: int
    severe_count: int
    fatal_count: int
    errors: list[str]
