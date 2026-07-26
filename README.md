# AI-Assisted Network & Building Intrusion Detection System
## Honeywell Forge Hackathon — AI-Driven HVAC Optimization

An autonomous AI agent that optimizes building HVAC energy consumption using real-time EnergyPlus simulation, an LLM-powered decision engine (Ollama/qwen2.5), and a deterministic safety-gated control core — all orchestrated through the Model Context Protocol (MCP).

### What This Does (60 seconds)

This system runs a physics-accurate EnergyPlus simulation of a single-zone Chicago office building, streams real-time telemetry (temperature, PMV comfort, CO₂, energy) into a SQLite database, and lets an AI agent — powered by a local LLM via Ollama — make autonomous HVAC setpoint decisions every hour. Every recommendation passes through a deterministic **Control Core** that enforces hard safety constraints (setpoint gaps, PMV bounds, deadbands, cooldown timers) before any actuator is touched. The agent implements three strategies: **occupied-hours comfort-energy nudges** (small setpoint adjustments within a tight PMV buffer), **explicit night setback** (2°C setpoint relaxation during unoccupied hours), and **optimal-start pre-conditioning** (gradual morning ramp-up before occupancy). Result: **10.74% energy savings with zero occupied-hours comfort penalty**.

---

## 🚀 Quick Start

### Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| **Python** | 3.10+ | `brew install python` or [python.org](https://python.org) |
| **EnergyPlus** | 24.2.0 | [github.com/NREL/EnergyPlus/releases](https://github.com/NREL/EnergyPlus/releases/tag/v24.2.0) |
| **Ollama** | Latest | `brew install ollama` or [ollama.com](https://ollama.com) |

### Setup

```bash
# 1. Clone the repository
git clone <repo-url> && cd honeywell

# 2. Run the setup script (creates venv, installs deps, pulls LLM)
chmod +x setup.sh && ./setup.sh

# 3. Copy and edit environment variables
cp .env.example .env
# Edit .env if your EnergyPlus is installed in a non-default location

# 4. Start Ollama (in a separate terminal)
ollama serve
```

### Run the Evaluation

```bash
# Run baseline vs AI comparison (takes ~30 seconds)
source .venv/bin/activate
python evaluation/engine.py

# Launch the dashboard
streamlit run dashboard/app.py --server.port 8501
# Open http://localhost:8501
```

### Run the MCP Server (for live LLM tool-calling)

```bash
source agent/mcp_server/.venv/bin/activate
python agent/mcp_server/server.py
```

### Docker (Alternative)

```bash
docker-compose up --build
# Dashboard: http://localhost:8501
```

---

## 📁 Project Structure

```
honeywell/
├── simulation/          # EnergyPlus runtime wrapper & IDF model
│   ├── models/          # baseline_office.idf (single-zone Chicago office)
│   ├── weather/         # chicago.epw (TMY3 weather data)
│   ├── runtime_wrapper.py  # Python↔EnergyPlus bridge via pyenergyplus
│   ├── runner.py        # High-level simulation orchestrator
│   └── config.py        # EMS variable/actuator mappings
├── telemetry/           # SQLite telemetry pipeline
│   ├── log_parser.py    # Parses EnergyPlus CSV → SQLite snapshots
│   └── __init__.py
├── control/             # Deterministic safety-gated control core
│   ├── core.py          # ControlCore — all safety checks (gap, PMV, delta, cooldown)
│   ├── actions.py       # Action catalog & type definitions
│   ├── constraints.py   # ASHRAE 55 comfort constraints
│   └── test_recommendation_bridge.py  # Integration tests
├── agent/
│   └── mcp_server/      # MCP Server (FastMCP / STDIO transport)
│       ├── server.py    # 3 MCP tools: get_state_summary, analyze_trends, recommend_action
│       ├── verify_tools.py  # Tool verification tests
│       └── requirements.txt
├── evaluation/          # Comparison engine
│   ├── engine.py        # Runs baseline vs AI scenarios, computes metrics
│   ├── comparison_metrics.json
│   └── comparison_timeseries.csv
├── dashboard/
│   └── app.py           # Streamlit dashboard — side-by-side visualization
├── docs/
│   └── architecture.md  # Full architecture document
├── Dockerfile
├── docker-compose.yml
├── setup.sh
├── .env.example
└── README.md
```

---

## 📊 Final Results

| Metric | Baseline | AI-Controlled | Delta |
|:---|:---:|:---:|:---:|
| **Total Energy** | 189.98 kWh | 169.58 kWh | **-10.74%** |
| **Occupied Comfort Violations** | 615 mins | 615 mins | **0 (exact parity)** |
| **Peak Demand** | 4.67 kW | 5.46 kW | **+16.9%** |
| **Interventions** | 0 | 22 (19 nudge + 3 setback) | — |

---

## 🏗️ Architecture

See [docs/architecture.md](docs/architecture.md) for the full technical deep-dive, including:
- MCP tool-calling architecture (Ollama ↔ FastMCP ↔ Control Core)
- Deterministic safety gate design
- Self-correction retry loop
- Optimal start pre-conditioning strategy
- Peak demand physical explanation

---

## 📄 License

MIT
