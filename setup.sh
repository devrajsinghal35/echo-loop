#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────
# setup.sh — One-command setup for the AI-Assisted HVAC Control System
# ──────────────────────────────────────────────────────────────────────────
set -euo pipefail

PYTHON="${PYTHON:-python3}"
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   AI-Assisted HVAC Control — Setup Script                   ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── 1. Check Python ──────────────────────────────────────────────────────
echo "▶ Checking Python..."
if ! command -v "$PYTHON" &>/dev/null; then
    echo "  ✘ Python 3.10+ is required but not found. Install from python.org"
    exit 1
fi
PY_VERSION=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  ✓ Found Python $PY_VERSION"

# ── 2. Check EnergyPlus ──────────────────────────────────────────────────
echo "▶ Checking EnergyPlus..."
EP_FOUND=false
for ep_dir in /usr/local/EnergyPlus-24-2-0 /Applications/EnergyPlus-24-2-0 "$HOME/EnergyPlus-24-2-0"; do
    if [ -d "$ep_dir" ]; then
        echo "  ✓ Found EnergyPlus at $ep_dir"
        EP_FOUND=true
        break
    fi
done
if [ "$EP_FOUND" = false ]; then
    echo "  ⚠ EnergyPlus 24.2.0 not found in standard locations."
    echo "    Download from: https://github.com/NREL/EnergyPlus/releases/tag/v24.2.0"
    echo "    Set ENERGYPLUS_DIR in .env after installation."
fi

# ── 3. Create project-level virtual environment ─────────────────────────
echo "▶ Creating project virtual environment (.venv)..."
if [ ! -d "$PROJECT_ROOT/.venv" ]; then
    $PYTHON -m venv "$PROJECT_ROOT/.venv"
    echo "  ✓ Created .venv"
else
    echo "  ✓ .venv already exists"
fi
source "$PROJECT_ROOT/.venv/bin/activate"

# ── 4. Install Python dependencies ──────────────────────────────────────
echo "▶ Installing Python dependencies..."
pip install --quiet --upgrade pip
pip install --quiet streamlit pandas

# ── 5. Create MCP server virtual environment ─────────────────────────────
echo "▶ Setting up MCP server environment..."
MCP_DIR="$PROJECT_ROOT/agent/mcp_server"
if [ ! -d "$MCP_DIR/.venv" ]; then
    $PYTHON -m venv "$MCP_DIR/.venv"
    echo "  ✓ Created agent/mcp_server/.venv"
else
    echo "  ✓ agent/mcp_server/.venv already exists"
fi
source "$MCP_DIR/.venv/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet -r "$MCP_DIR/requirements.txt"
pip install --quiet streamlit pandas

# Restore project venv
source "$PROJECT_ROOT/.venv/bin/activate"

# ── 6. Pull Ollama model ────────────────────────────────────────────────
echo "▶ Checking Ollama..."
if command -v ollama &>/dev/null; then
    echo "  ✓ Ollama found"
    echo "  ▶ Pulling qwen2.5:7b-instruct (this may take a few minutes on first run)..."
    ollama pull qwen2.5:7b-instruct 2>/dev/null || echo "  ⚠ Could not pull model. Ensure 'ollama serve' is running."
else
    echo "  ⚠ Ollama not found. Install from https://ollama.com"
    echo "    Then run: ollama pull qwen2.5:7b-instruct"
fi

# ── 7. Create .env from template ────────────────────────────────────────
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
    echo "▶ Created .env from .env.example — edit if needed."
else
    echo "▶ .env already exists — skipping."
fi

# ── 8. Clean up scratch files ────────────────────────────────────────────
echo "▶ Keeping scratch files..."
# rm -f "$PROJECT_ROOT"/scratch_*.py
# echo "  ✓ Removed scratch files"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   ✅  Setup complete!                                       ║"
echo "║                                                              ║"
echo "║   Quick start:                                               ║"
echo "║     source .venv/bin/activate                                ║"
echo "║     python evaluation/engine.py       # Run comparison       ║"
echo "║     streamlit run dashboard/app.py    # Launch dashboard     ║"
echo "╚══════════════════════════════════════════════════════════════╝"
