from pathlib import Path
from telemetry.models import LogSummary

def parse_eplus_err_log(log_path: str | Path) -> LogSummary:
    """
    Parses the EnergyPlus .err file to summarize warnings and errors.
    Memory efficient: handles very large logs by reading line-by-line.
    """
    log_path = Path(log_path)
    
    warnings = 0
    severes = 0
    fatals = 0
    error_messages = []
    exec_time = 0.0
    
    if not log_path.exists():
        return LogSummary(0.0, 0, 0, 0, ["Log file not found."])

    # We read line by line to prevent memory truncation on massive files
    with open(log_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if "** Warning **" in line:
                warnings += 1
            elif "** Severe  **" in line:
                severes += 1
                error_messages.append(line.replace("** Severe  **", "").strip())
            elif "**  Fatal  **" in line or "** Fatal **" in line:
                fatals += 1
                error_messages.append(line.replace("**  Fatal  **", "").strip())
            elif "Elapsed Time=" in line:
                # Try to parse execution time if present on the last line
                try:
                    parts = line.split("Elapsed Time=")[1]
                    # Parse "00hr 00min  0.10sec" roughly
                    if "sec" in parts:
                        sec_str = parts.split("min")[1].replace("sec", "").strip()
                        exec_time = float(sec_str)
                except (IndexError, ValueError):
                    pass
                    
    return LogSummary(
        execution_time_s=exec_time,
        warning_count=warnings,
        severe_count=severes,
        fatal_count=fatals,
        errors=error_messages
    )
