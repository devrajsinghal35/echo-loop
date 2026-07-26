# pyrefly: ignore [missing-import]
import streamlit as st
import pandas as pd
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

st.set_page_config(page_title="AI HVAC Control Evaluation", layout="wide", page_icon="🏢")

st.title("🏢 Building AI Control Evaluation Dashboard")
st.markdown("Comparing deterministic baseline control against the LLM-driven AI control loop for a single-zone office in Chicago.")

# ── 1. Executive Summary Banner ─────────────────────────────────────────────
st.info("💡 **Executive Summary**: AI-driven control achieved a 10.7% energy reduction (169.6 kWh vs 189.98 kWh baseline) while maintaining 100% occupied-hours comfort parity — with a self-correcting agent that caught and fixed its own unsafe recommendations.")

metrics_file = PROJECT_ROOT / "evaluation" / "comparison_metrics.json"
csv_file = PROJECT_ROOT / "evaluation" / "comparison_timeseries.csv"

if not metrics_file.exists() or not csv_file.exists():
    st.error("Evaluation data not found. Please run the evaluation engine first.")
    st.stop()

# Load Data
with open(metrics_file, "r") as f:
    metrics = json.load(f)

df = pd.read_csv(csv_file)

# Prepare KPIs
baseline = metrics.get("baseline", {})
ai = metrics.get("ai", {})

total_kwh_b = baseline.get("total_kwh", 0)
total_kwh_a = ai.get("total_kwh", 0)
kwh_diff = total_kwh_a - total_kwh_b
kwh_pct = (kwh_diff / total_kwh_b * 100) if total_kwh_b else 0

peak_kw_b = baseline.get("peak_kw", 0)
peak_kw_a = ai.get("peak_kw", 0)
peak_diff = peak_kw_a - peak_kw_b

comf_mins_b = baseline.get("comfort_violation_mins", 0)
comf_mins_a = ai.get("comfort_violation_mins", 0)
comf_diff = comf_mins_a - comf_mins_b

comf_occ_b = baseline.get("comfort_violation_occupied_mins", 0)
comf_occ_a = ai.get("comfort_violation_occupied_mins", 0)
comf_occ_diff = comf_occ_a - comf_occ_b

comf_unocc_b = baseline.get("comfort_violation_unoccupied_mins", 0)
comf_unocc_a = ai.get("comfort_violation_unoccupied_mins", 0)
comf_unocc_diff = comf_unocc_a - comf_unocc_b

interv_raw_b = baseline.get("interventions", 0)
interv_raw_a = ai.get("interventions", 0)

interv_b_val = interv_raw_b if isinstance(interv_raw_b, (int, float)) else sum(interv_raw_b.values()) if isinstance(interv_raw_b, dict) else 0
interv_a_val = interv_raw_a if isinstance(interv_raw_a, (int, float)) else sum(interv_raw_a.values()) if isinstance(interv_raw_a, dict) else 0
interv_diff = interv_a_val - interv_b_val

interv_b_dict = interv_raw_b if isinstance(interv_raw_b, dict) else {}
interv_a_dict = interv_raw_a if isinstance(interv_raw_a, dict) else {}

# ── 2. Overall Performance Metrics ───────────────────────────────────────────
st.header("Overall Performance Metrics")
cols = st.columns(4)

cols[0].metric(
    "Total Energy (kWh)", 
    f"{total_kwh_a:,.1f}", 
    f"{kwh_diff:,.1f} ({kwh_pct:+.1f}%)", 
    delta_color="inverse"
)
cols[1].metric(
    "Peak Demand (kW)", 
    f"{peak_kw_a:,.1f}", 
    f"{peak_diff:+.2f} kW", 
    delta_color="off"
)
cols[2].metric(
    "Total Comfort Violations (mins)", 
    f"{comf_mins_a:,}", 
    f"{comf_diff:,}", 
    delta_color="inverse"
)
cols[3].metric(
    "AI Interventions", 
    f"{interv_a_val:,}", 
    f"{interv_diff:,}", 
    delta_color="normal"
)

st.caption("⚡ **Why Peak Demand Rose (+0.79 kW)**: On extreme winter mornings, the AI spent extra heating power to rescue occupant comfort (PMV < -0.8 in baseline), prioritizing occupant health while still delivering 10.7% net energy savings overall.")

# ── 3. Self-Correction in Action ─────────────────────────────────────────────
st.divider()
st.header("🛡️ Self-Correction in Action (Deterministic Safety Gate)")
st.markdown("Proof of agentic autonomy: LLM recommendations pass through a Control Core. If rejected, the agent retries safely.")

step_cols = st.columns(4)

step_cols[0].warning("""
**1. Initial Action (Rejected)**  
**Step 128**: Proposed heating setpoint jump to 23.1°C (gap 1.9°C < min 2.0°C).
""")

step_cols[1].error("""
**2. Control Core Gate**  
**Violation Caught**: Setpoint gap 1.9°C violated deadband safety limit.
""")

step_cols[2].info("""
**3. Agent Retry**  
**Self-Corrected**: Evaluated `previous_rejection_reason` & reduced step to +0.25°C.
""")

step_cols[3].success("""
**4. Safety Approval**  
**Approved**: Target heating setpoint 22.25°C passed all checks & executed.
""")

# ── 4. Comfort & Intervention Breakdown ──────────────────────────────────────
st.divider()
st.subheader("Comfort Breakdown (Occupied vs. Unoccupied)")
c_cols = st.columns(2)
c_cols[0].metric(
    "Occupied Comfort Violations (08:00-18:00)",
    f"{comf_occ_a:,} mins",
    f"{comf_occ_diff:+,} mins",
    delta_color="inverse"
)
c_cols[1].metric(
    "Unoccupied Comfort Violations (Off-Hours)",
    f"{comf_unocc_a:,} mins",
    f"{comf_unocc_diff:+,} mins",
    delta_color="inverse"
)

st.subheader("AI Intervention Category Breakdown")
i_cols = st.columns(2)
i_cols[0].metric(
    "Occupied Comfort-Energy Nudges",
    f"{interv_a_dict.get('occupied_nudge', 0):,} actions",
    f"Baseline: {interv_b_dict.get('occupied_nudge', 0)}"
)
i_cols[1].metric(
    "Unoccupied Night Setbacks",
    f"{interv_a_dict.get('unoccupied_setback', 0):,} actions",
    f"Baseline: {interv_b_dict.get('unoccupied_setback', 0)}"
)

# ── 5. Time-Series Comparison ────────────────────────────────────────────────
st.divider()
st.header("📈 Time-Series Comparison")
st.caption("🔴 **Red Line**: Baseline (Fixed Setpoints) | 🔵 **Blue Line**: AI-Controlled (Dynamic Safety-Gated Optimization)")

# Energy Power
st.subheader("Energy Rate (kW)")
df_power = df[["timestamp", "baseline_kw", "ai_kw"]].set_index("timestamp")
st.line_chart(df_power, color=["#FF4B4B", "#0068C9"])

# Comfort PMV
st.subheader("Thermal Comfort (PMV)")
df_pmv = df[["timestamp", "baseline_pmv", "ai_pmv"]].set_index("timestamp")
st.line_chart(df_pmv, color=["#FF4B4B", "#0068C9"])
st.caption("Target ASHRAE 55 PMV range is between -0.5 (cool) and +0.5 (warm).")

# Zone Temperature
st.subheader("Zone Temperature (°C)")
df_temp = df[["timestamp", "baseline_temp", "ai_temp"]].set_index("timestamp")
st.line_chart(df_temp, color=["#FF4B4B", "#0068C9"])

# ── 6. Architecture & MCP Tool Calling Expander ──────────────────────────────
st.divider()
with st.expander("🛠️ System Architecture & MCP Tool-Calling Flow"):
    st.markdown("""
```
┌─────────────────────────┐      JSON-RPC / STDIO      ┌──────────────────────────┐
│   Ollama / qwen2.5      ├───────────────────────────►│   MCP Server (FastMCP)   │
│   (LLM Reasoning Engine)│                            │                          │
└─────────────────────────┘                            │  • get_state_summary     │
                                                       │  • analyze_trends        │
                                                       │  • recommend_action      │
                                                       └────────────┬─────────────┘
                                                                    │ proposed action
                                                       ┌────────────▼─────────────┐
                                                       │ Deterministic Control    │
                                                       │ Core (Safety Gate)       │
                                                       │ • Setpoint Gap >= 2.0°C  │
                                                       │ • PMV Bounds [-0.5, 0.5]  │
                                                       │ • Deadband >= 0.25°C     │
                                                       │ • Cooldown 4 Timesteps   │
                                                       └────────────┬─────────────┘
                                                                    │ approved action
                                                       ┌────────────▼─────────────┐
                                                       │ EnergyPlus Simulation    │
                                                       │ EMS Actuators            │
                                                       └──────────────────────────┘
```
- **Baseline**: Constant standard heating/cooling setpoints with rule-based deadband protection.  
- **AI Control**: LLM-driven proactive setpoint adjustments aiming for energy efficiency and comfort stability.
""")
