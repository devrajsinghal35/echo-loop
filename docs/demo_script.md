# 3-Minute Demo Script: AI-Assisted HVAC Control System

---

## ⏱️ Timeline & Walkthrough

### 0:00 – 0:30 | Introduction & Baseline Run
- **Presenter**: "Welcome to our AI-Assisted Building HVAC Optimization System. HVAC accounts for ~40% of commercial building energy consumption. Standard BMS systems use fixed temperature schedules that waste energy overnight and can't adapt to dynamic weather changes."
- **Action**: Run `python evaluation/engine.py` in terminal.
- **Presenter**: "Watch as we spin up a physics-accurate EnergyPlus simulation of a Chicago office building. First, it runs the fixed-schedule baseline scenario across summer and winter design days."

---

### 0:30 – 1:15 | Live Telemetry & MCP Tool Calls
- **Presenter**: "As EnergyPlus runs, snapshot telemetry—zone temperature, PMV thermal comfort, CO₂ levels, and power consumption—is streamed every 15 minutes into a SQLite telemetry pipeline."
- **Action**: Highlight terminal output showing live MCP tool calls (`get_state_summary`, `analyze_trends`, `recommend_action`).
- **Presenter**: "Our AI Agent operates via the Model Context Protocol (FastMCP). Every hour, the agent inspects building trends using `analyze_trends` and Formulates a candidate HVAC action via `recommend_action` powered by local LLM reasoning (`qwen2.5:7b-instruct`)."

---

### 1:15 – 2:00 | Safety Gate & Self-Correction Loop
- **Presenter**: "Crucially, an LLM never touches building physical actuators directly. Every recommendation is passed to our **Deterministic Control Core**."
- **Action**: Show rejection log in terminal (e.g., Step 128).
- **Presenter**: "Notice Step 128 here: The LLM initially proposed a setpoint change that would make the heating/cooling gap 1.9°C—violating our hard 2.0°C deadband safety constraint. The Control Core rejected it immediately! The engine fed the rejection reason back to the agent, which self-corrected on the next step to a safe 0.25°C nudge that passed all safety checks."

---

### 2:00 – 3:00 | Dashboard & Proof of Results
- **Action**: Switch to the Streamlit Dashboard browser tab (`http://localhost:8501`).
- **Presenter**: "Here on the Streamlit dashboard, we see the side-by-side verification results:"
  - **10.74% Total Energy Savings** (189.98 kWh baseline down to 169.58 kWh AI-controlled).
  - **Exact Occupied Comfort Parity** (615 minutes of occupied comfort violations in baseline vs. 615 minutes under AI control).
  - **Physical Peak Demand Insight**: Point out the winter morning peak (+16.9%). "The AI spent extra heating power on extreme winter mornings to rescue occupant comfort when PMV dropped below -0.8, proving it prioritizes human health while still delivering >10% net energy savings overall."
- **Presenter**: "Thank you! Everything is containerized with Docker and ready for deployment."
