"""
agent/mcp_server/server.py — MCP Server (FastMCP / STDIO transport)

Exposes building control tools to an MCP client. All tools read live data
from the telemetry SQLite database and EnergyPlus logs.

Start with:
    .venv/bin/python server.py
"""

import json
import sqlite3
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# ── Project root (two levels up from this file) ──────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "telemetry.db"
ERR_LOG_PATH = PROJECT_ROOT / "simulation" / "logs" / "eplusout.err"

# Valid action_type values from control/actions.py
VALID_ACTION_TYPES = {
    "adjust_heating_setpoint",
    "adjust_cooling_setpoint",
    "no_action",
}

# ── Server instance ───────────────────────────────────────────────────────
mcp = FastMCP(
    name="HoneywellBuildingControl",
    instructions=(
        "AI-assisted building control agent for a single-zone office in Chicago. "
        "Always call get_state_summary first to understand the current state, "
        "then analyze_trends to understand trajectory, "
        "then recommend_action to produce a validated control decision."
    ),
)


# ── Helpers ───────────────────────────────────────────────────────────────

def _query_db(sql: str, params: tuple = ()) -> list[dict]:
    """Run a read-only SQLite query and return rows as dicts."""
    if not DB_PATH.exists():
        return []
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


# ── Tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
def get_state_summary() -> dict:
    """
    Return a structured summary of the current building state.

    Reads the most recent non-warmup snapshot from telemetry. Includes zone
    temperature, energy consumption rate, CO2 concentration, and Fanger PMV
    thermal comfort index.

    Returns:
        zone_temp_c: Zone mean air temperature (°C)
        energy_rate_w: Combined heating+cooling power draw (W)
        iaq_co2_ppm: Zone CO2 concentration (ppm)
        comfort_pmv: Fanger PMV index (-3 cold … +3 hot; ASHRAE band [-0.5, 0.5])
        timestep: Integer step index
        timestamp: Label string
        comfort_status: "comfortable" | "too_cold" | "too_warm"
        temp_status: "in_range" | "below_min" | "above_max"
        co2_status: "ok" | "elevated"
    """
    rows = _query_db(
        "SELECT * FROM snapshots WHERE is_warmup = 0 ORDER BY id DESC LIMIT 1"
    )
    if not rows:
        return {"error": "No telemetry data available. Run the simulation first."}

    r = rows[0]
    pmv = r["comfort_pmv"]
    temp = r["zone_temp_c"]
    co2 = r["iaq_co2_ppm"]

    return {
        "timestep": r["timestep"],
        "timestamp": r["timestamp"],
        "zone_temp_c": round(temp, 2),
        "energy_rate_w": round(r["energy_rate_w"], 1),
        "iaq_co2_ppm": round(co2, 1),
        "comfort_pmv": round(pmv, 3),
        "comfort_status": (
            "too_cold" if pmv < -0.5 else
            "too_warm" if pmv > 0.5 else
            "comfortable"
        ),
        "temp_status": (
            "below_min" if temp < 20.0 else
            "above_max" if temp > 26.0 else
            "in_range"
        ),
        "co2_status": "elevated" if co2 > 1000 else "ok",
    }


@mcp.tool()
def analyze_trends(window_steps: int = 24) -> dict:
    """
    Analyse the last N timesteps of telemetry for trend direction.

    Args:
        window_steps: How many recent non-warmup timesteps to analyse
                      (default 24 = 6 hours at 15-min resolution).

    Returns:
        temp_trend, energy_trend, pmv_trend, co2_trend: each "rising" | "falling" | "stable"
        avg_pmv: Average PMV over the window
        avg_temp_c: Average zone temperature over the window
        avg_energy_w: Average energy rate over the window
        comfort_violation_pct: % of window timesteps where PMV was outside [-0.5, 0.5]
        sample_count: Actual number of rows used
    """
    rows = _query_db(
        "SELECT * FROM snapshots WHERE is_warmup = 0 ORDER BY id DESC LIMIT ?",
        (window_steps,),
    )
    if len(rows) < 2:
        return {"error": f"Not enough telemetry data (need ≥2 rows, got {len(rows)})."}

    # Reverse so oldest→newest for trend direction
    rows = list(reversed(rows))

    def trend(values: list[float], threshold: float = 0.05) -> str:
        if len(values) < 2:
            return "stable"
        delta = values[-1] - values[0]
        span = max(abs(v) for v in values) or 1.0
        relative = delta / span
        if relative > threshold:
            return "rising"
        if relative < -threshold:
            return "falling"
        return "stable"

    temps  = [r["zone_temp_c"]   for r in rows]
    energy = [r["energy_rate_w"] for r in rows]
    pmvs   = [r["comfort_pmv"]   for r in rows]
    co2s   = [r["iaq_co2_ppm"]   for r in rows]

    n = len(rows)
    violation_count = sum(1 for p in pmvs if p < -0.5 or p > 0.5)

    return {
        "sample_count": n,
        "window_steps_requested": window_steps,
        "temp_trend":   trend(temps),
        "energy_trend": trend(energy),
        "pmv_trend":    trend(pmvs),
        "co2_trend":    trend(co2s),
        "avg_temp_c":   round(sum(temps)  / n, 2),
        "avg_energy_w": round(sum(energy) / n, 1),
        "avg_pmv":      round(sum(pmvs)   / n, 3),
        "avg_co2_ppm":  round(sum(co2s)   / n, 1),
        "comfort_violation_pct": round(100 * violation_count / n, 1),
    }


@mcp.tool()
def diagnose_errors() -> dict:
    """
    Parse the most recent EnergyPlus run log and summarise errors.

    Handles logs of any size line-by-line to avoid memory issues.

    Returns:
        warning_count, severe_count, fatal_count: integer counts
        execution_time_s: run time extracted from the log footer
        recent_errors: last up to 5 severe/fatal error messages
        status: "healthy" | "warnings_only" | "errors_present" | "fatal"
    """
    if not ERR_LOG_PATH.exists():
        return {"error": f"Log file not found: {ERR_LOG_PATH}"}

    warnings, severes, fatals = 0, 0, 0
    exec_time = 0.0
    recent_errors: list[str] = []

    with open(ERR_LOG_PATH, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            stripped = line.strip()
            if "** Warning **" in stripped:
                warnings += 1
            elif "** Severe  **" in stripped:
                severes += 1
                recent_errors.append(stripped[:200])
            elif "**  Fatal  **" in stripped:
                fatals += 1
                recent_errors.append(stripped[:200])
            elif "Elapsed Time=" in stripped:
                # e.g. "Elapsed Time=00hr 00min  0.06sec"
                try:
                    parts = stripped.split("Elapsed Time=")[1]
                    h = int(parts[0:2])
                    m = int(parts[5:7])
                    s = float(parts[12:].replace("sec", "").strip())
                    exec_time = h * 3600 + m * 60 + s
                except Exception:
                    pass

    if fatals:
        status = "fatal"
    elif severes:
        status = "errors_present"
    elif warnings:
        status = "warnings_only"
    else:
        status = "healthy"

    return {
        "status": status,
        "warning_count": warnings,
        "severe_count": severes,
        "fatal_count": fatals,
        "execution_time_s": exec_time,
        "recent_errors": recent_errors[-5:],
    }


@mcp.tool()
def recommend_action(
    target: str = "balanced",
    constraint_mode: str = "strict",
    previous_rejection_reason: str = None,
    current_heating_sp: float = 21.0,
    current_cooling_sp: float = 24.0,
) -> dict:
    """
    Recommend a control action based on current building state and trends.

    The output is always schema-compatible with the deterministic Control Core:
    action_type must be one of the catalog values, target_value must be within
    the actuator's hard bounds, and the rationale must cite the data.

    Args:
        target: Optimisation objective — "energy_efficiency" | "comfort" | "balanced"
        constraint_mode: "strict" (ASHRAE 55, PMV in [-0.5, 0.5]) or
                         "relaxed" (minor PMV violations allowed to save energy)
        previous_rejection_reason: Reason string from a prior rejection, if self-correcting.
        current_heating_sp: The current heating setpoint in °C.
        current_cooling_sp: The current cooling setpoint in °C.

    Returns:
        action_type: "adjust_cooling_setpoint" | "adjust_heating_setpoint" | "no_action"
        target_value: New setpoint in °C (null when no_action)
        confidence: 0.0–1.0
        rationale: Human-readable explanation citing current data
        schema_version: "1.0" (for downstream validation)
    """
    # Read current state
    rows = _query_db(
        "SELECT * FROM snapshots WHERE is_warmup = 0 ORDER BY id DESC LIMIT 24"
    )
    if not rows:
        return {
            "action_type": "no_action",
            "target_value": None,
            "confidence": 0.0,
            "rationale": "No telemetry data available.",
            "schema_version": "1.0",
        }

    latest = rows[0]
    pmv   = latest["comfort_pmv"]
    temp  = latest["zone_temp_c"]
    co2   = latest["iaq_co2_ppm"]
    e_w   = latest["energy_rate_w"]

    pmv_strict_min, pmv_strict_max = -0.5, 0.5
    pmv_relaxed_min, pmv_relaxed_max = -1.0, 1.0
    pmv_min = pmv_strict_min if constraint_mode == "strict" else pmv_relaxed_min
    pmv_max = pmv_strict_max if constraint_mode == "strict" else pmv_relaxed_max

    action_type   = "no_action"
    target_value  = None
    confidence    = 0.5
    
    retry_context = f" (Self-Correcting: {previous_rejection_reason})" if previous_rejection_reason else ""
    rationale_parts: list[str] = [
        f"State: temp={temp:.1f}°C, PMV={pmv:.2f}, CO2={co2:.0f}ppm, energy={e_w:.0f}W. "
        f"Target={target}, constraints={constraint_mode}.{retry_context}"
    ]

    # Adjust the aggressiveness of deltas if we are retrying after a bound/gap rejection
    max_delta = 0.25 if previous_rejection_reason else 2.0
    delta_mult = 0.5 if previous_rejection_reason else 1.0

    # ── Decision rules ────────────────────────────────────────────────────
    
    # Calculate if occupied (approx 08:00 to 18:00)
    # 96 steps per day (15 min each). 8 AM = step 32, 6 PM = step 72.
    step_in_day = (latest["timestep"] - 1) % 96 + 1
    is_occupied = (32 <= step_in_day <= 72)
    # ── Rules Engine ─────────────────────────────────────────────────────────

    # Pre-conditioning (Optimal Start): 06:00 to 08:00
    # Gradually ramp setpoints from night setback (20.0/25.0) back to occupied targets (22.0/23.0).
    # Agent is called every 4 timesteps (hourly). With 2 calls in the window (steps 24, 28),
    # a 1.0°C ramp per call recovers the full 2.0°C in two equal steps — halving peak recovery load.
    if 24 <= step_in_day < 32:
        ramp_step = 1.0  # 1.0°C per hour × 2 hours = 2.0°C full recovery
        
        need_cool_ramp = current_cooling_sp > 23.0
        need_heat_ramp = current_heating_sp < 22.0
        
        # Prioritize whichever direction HELPS comfort (avoids PMV safety rejections):
        # Hot (PMV > 0) → ramp cooling down first (reduces overheating)
        # Cold (PMV < 0) → ramp heating up first (reduces undercooling)
        if pmv >= 0 and need_cool_ramp:
            action_type = "adjust_cooling_setpoint"
            delta = min(current_cooling_sp - 23.0, ramp_step)
            target_value = round(current_cooling_sp - delta, 2)
            confidence = 0.9
            rationale_parts.append(f"Pre-conditioning (Optimal Start). Gradual ramp: cooling SP -{delta:.2f}°C to {target_value}°C.")
        elif pmv < 0 and need_heat_ramp:
            action_type = "adjust_heating_setpoint"
            delta = min(22.0 - current_heating_sp, ramp_step)
            target_value = round(current_heating_sp + delta, 2)
            confidence = 0.9
            rationale_parts.append(f"Pre-conditioning (Optimal Start). Gradual ramp: heating SP +{delta:.2f}°C to {target_value}°C.")
        elif need_cool_ramp:
            action_type = "adjust_cooling_setpoint"
            delta = min(current_cooling_sp - 23.0, ramp_step)
            target_value = round(current_cooling_sp - delta, 2)
            confidence = 0.9
            rationale_parts.append(f"Pre-conditioning (Optimal Start). Gradual ramp: cooling SP -{delta:.2f}°C to {target_value}°C.")
        elif need_heat_ramp:
            action_type = "adjust_heating_setpoint"
            delta = min(22.0 - current_heating_sp, ramp_step)
            target_value = round(current_heating_sp + delta, 2)
            confidence = 0.9
            rationale_parts.append(f"Pre-conditioning (Optimal Start). Gradual ramp: heating SP +{delta:.2f}°C to {target_value}°C.")
        else:
            rationale_parts.append("Pre-conditioning complete. Setpoints at occupied targets.")
            confidence = 0.9

    # If unoccupied, aggressive energy saving (setback)
    elif not is_occupied:
        # Instead of explicitly demanding 16.0 or 30.0 which breaks the max_delta rule (2.0°C) and ruins morning recovery,
        # we issue an unoccupied_setback with a 2.0°C target drift, but we only do this ONCE.
        # This keeps the setback at exactly 2.0°C off the baseline, allowing a 1-step recovery at 08:00.
        if current_heating_sp > 20.0 or current_cooling_sp < 25.0:
            action_type = "unoccupied_setback"
            target_value = 2.0
            confidence = 0.9
            rationale_parts.append("Building unoccupied. Relaxing setpoints by 2.0°C to save energy.")
        else:
            rationale_parts.append("Building unoccupied and setpoints already at optimal 2.0°C setback. No action needed.")
            confidence = 0.9

    # Priority 1: comfort rescue (PMV out of band — always override energy) IF OCCUPIED
    elif pmv < pmv_min:
        # Too cold — raise heating setpoint to increase heating output
        action_type  = "adjust_heating_setpoint"
        # PMV to Temp roughly 1:3 ratio. Ensure minimum step of 0.25.
        delta = max(0.25, min(abs(pmv - pmv_min) * 3.0 * delta_mult, max_delta))
        target_value = round(current_heating_sp + delta, 2)
        target_value = max(16.0, min(24.0, target_value))
        confidence = min(0.9, 0.5 + abs(pmv - pmv_min) * 0.3)
        rationale_parts.append(
            f"PMV={pmv:.2f} is below {pmv_min} (too cold). "
            f"Recommending raise heating SP by {delta:.2f}°C to {target_value}°C to increase heating."
        )

    elif pmv > pmv_max:
        # Too warm — lower cooling setpoint to increase cooling output
        action_type = "adjust_cooling_setpoint"
        # PMV to Temp roughly 1:3 ratio. Ensure minimum step of 0.25.
        delta = max(0.25, min(abs(pmv - pmv_max) * 3.0 * delta_mult, max_delta))
        target_value = round(current_cooling_sp - delta, 2)
        target_value = max(22.0, min(30.0, target_value))
        confidence = min(0.9, 0.5 + abs(pmv - pmv_max) * 0.3)
        rationale_parts.append(
            f"PMV={pmv:.2f} is above {pmv_max} (too warm). "
            f"Recommending lower cooling SP by {delta:.2f}°C to {target_value}°C to increase cooling."
        )

    # Priority 2: energy optimisation when comfort is within the target operating range
    elif target in ("energy_efficiency", "balanced") and pmv_min <= pmv <= pmv_max:
        # Define internal comfort buffer: [-0.35, 0.35] during occupied hours / balanced target
        # This reserves [-0.5, 0.5] as the hard safety floor, preventing energy nudges from causing violations.
        buffer_min, buffer_max = -0.35, 0.35
        
        if is_occupied and pmv < buffer_min:
            # PMV is between -0.5 and -0.35. Approaching cold boundary!
            # Proactively rescue comfort back into [-0.35, 0.35] range instead of saving energy.
            action_type = "adjust_heating_setpoint"
            delta = 0.25
            target_value = round(current_heating_sp + delta, 2)
            target_value = max(16.0, min(24.0, target_value))
            confidence = 0.75
            rationale_parts.append(
                f"PMV={pmv:.2f} is in buffer zone [{pmv_min}, {buffer_min}]. "
                f"Proactively nudging heating SP up by {delta}°C to maintain comfort margin."
            )
        elif is_occupied and pmv > buffer_max:
            # PMV is between 0.35 and 0.5. Approaching warm boundary!
            action_type = "adjust_cooling_setpoint"
            delta = 0.25
            target_value = round(current_cooling_sp - delta, 2)
            target_value = max(22.0, min(30.0, target_value))
            confidence = 0.75
            rationale_parts.append(
                f"PMV={pmv:.2f} is in buffer zone [{buffer_max}, {pmv_max}]. "
                f"Proactively nudging cooling SP down by {delta}°C to maintain comfort margin."
            )
        elif e_w > 1500:
            # Safely inside internal comfort buffer [-0.35, 0.35] — OK to nudge setpoints to save energy
            if pmv < 0:
                # Cooler side of buffer: Nudge heating setpoint down slightly
                action_type = "adjust_heating_setpoint"
                delta = 0.25 if previous_rejection_reason else 0.5
                target_value = round(current_heating_sp - delta, 1)
                confidence = 0.65
                rationale_parts.append(
                    f"PMV={pmv:.2f} safely within comfort buffer [{buffer_min}, {buffer_max}]. Energy={e_w:.0f}W is high. "
                    f"Nudging heating SP down by {delta}°C to save energy."
                )
            else:
                # Warmer side of buffer: Nudge cooling setpoint up slightly
                action_type = "adjust_cooling_setpoint"
                delta = 0.25 if previous_rejection_reason else 0.5
                target_value = round(current_cooling_sp + delta, 1)
                confidence = 0.65
                rationale_parts.append(
                    f"PMV={pmv:.2f} safely within comfort buffer [{buffer_min}, {buffer_max}]. Energy={e_w:.0f}W is high. "
                    f"Nudging cooling SP up by {delta}°C to save energy."
                )
        else:
            rationale_parts.append(
                f"Comfort is optimal (PMV={pmv:.2f}) and energy is acceptable ({e_w:.0f}W). "
                "No action needed."
            )
            confidence = 0.85

    else:
        rationale_parts.append("Conditions within acceptable range. No action needed.")
        confidence = 0.8

    return {
        "action_type":    action_type,
        "target_value":   target_value,
        "confidence":     round(confidence, 2),
        "rationale":      " ".join(rationale_parts),
        "schema_version": "1.0",
    }


# ── Entry point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    mcp.run(transport="stdio")
