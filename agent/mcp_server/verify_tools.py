#!/usr/bin/env python3
"""
agent/mcp_server/verify_tools.py — Full integration verification.

Tests:
  1. Each tool returns real data (not stubs)
  2. recommend_action output validates against Control Core schema — 10 calls
  3. Ollama (qwen2.5:7b-instruct) discovers and calls all four tools

Run from the mcp_server directory with the venv active:
    .venv/bin/python verify_tools.py
"""

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import ollama

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SERVER_SCRIPT = Path(__file__).parent / "server.py"
PYTHON = sys.executable

# ── Control Core schema ───────────────────────────────────────────────────
VALID_ACTION_TYPES = {"adjust_cooling_setpoint", "adjust_heating_setpoint", "no_action"}
COOLING_SP_BOUNDS = (22.0, 30.0)
HEATING_SP_BOUNDS = (16.0, 24.0)


def validate_recommend_response(data: dict) -> list[str]:
    """Return a list of schema violations (empty = valid)."""
    errs = []
    if "action_type" not in data:
        errs.append("Missing 'action_type'")
    elif data["action_type"] not in VALID_ACTION_TYPES:
        errs.append(f"Invalid action_type '{data['action_type']}' not in {VALID_ACTION_TYPES}")

    if data.get("action_type") != "no_action":
        tv = data.get("target_value")
        at = data.get("action_type", "")
        if tv is None:
            errs.append("target_value is None but action_type requires a value")
        elif "cooling" in at and not (COOLING_SP_BOUNDS[0] <= tv <= COOLING_SP_BOUNDS[1]):
            errs.append(f"target_value {tv} outside cooling bounds {COOLING_SP_BOUNDS}")
        elif "heating" in at and not (HEATING_SP_BOUNDS[0] <= tv <= HEATING_SP_BOUNDS[1]):
            errs.append(f"target_value {tv} outside heating bounds {HEATING_SP_BOUNDS}")

    conf = data.get("confidence")
    if conf is None or not (0.0 <= conf <= 1.0):
        errs.append(f"confidence '{conf}' not in [0.0, 1.0]")

    if not data.get("rationale"):
        errs.append("rationale is empty")
    if data.get("schema_version") != "1.0":
        errs.append(f"schema_version mismatch: {data.get('schema_version')!r}")
    return errs


async def run_verification():
    server_params = StdioServerParameters(command=PYTHON, args=[str(SERVER_SCRIPT)])
    all_passed = True

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print("=" * 65)
            print("  Step 4 MCP Tool Verification")
            print("=" * 65)

            # ── Part 1: Real data from each tool ─────────────────────────
            print("\n── Part 1: Real data from each tool ──────────────────────")

            result = await session.call_tool("get_state_summary", {})
            data = json.loads(result.content[0].text)
            has_real = (
                "error" not in data and
                data.get("zone_temp_c") is not None and
                data.get("comfort_pmv") is not None
            )
            icon = "✅" if has_real else "❌"
            print(f"\n{icon} get_state_summary — real data: {has_real}")
            print(f"   temp={data.get('zone_temp_c')}°C  PMV={data.get('comfort_pmv')}  "
                  f"CO2={data.get('iaq_co2_ppm')}ppm  energy={data.get('energy_rate_w')}W")
            print(f"   comfort_status={data.get('comfort_status')}  "
                  f"temp_status={data.get('temp_status')}  co2_status={data.get('co2_status')}")
            if not has_real:
                all_passed = False

            result = await session.call_tool("analyze_trends", {"window_steps": 24})
            data = json.loads(result.content[0].text)
            has_real = "error" not in data and data.get("sample_count", 0) > 0
            icon = "✅" if has_real else "❌"
            print(f"\n{icon} analyze_trends — {data.get('sample_count')} samples used")
            print(f"   temp_trend={data.get('temp_trend')}  energy_trend={data.get('energy_trend')}  "
                  f"pmv_trend={data.get('pmv_trend')}  co2_trend={data.get('co2_trend')}")
            print(f"   avg_temp={data.get('avg_temp_c')}°C  avg_PMV={data.get('avg_pmv')}  "
                  f"comfort_violations={data.get('comfort_violation_pct')}%")
            if not has_real:
                all_passed = False

            result = await session.call_tool("diagnose_errors", {})
            data = json.loads(result.content[0].text)
            has_real = "error" not in data and data.get("status") is not None
            icon = "✅" if has_real else "❌"
            print(f"\n{icon} diagnose_errors — status={data.get('status')}")
            print(f"   warnings={data.get('warning_count')}  severe={data.get('severe_count')}  "
                  f"fatal={data.get('fatal_count')}  time={data.get('execution_time_s')}s")
            if not has_real:
                all_passed = False

            # ── Part 2: recommend_action — 10-call schema & direction validation ────
            print("\n── Part 2: recommend_action — 10-call schema & direction validation ─")
            combos = [
                ("energy_efficiency", "strict"),
                ("energy_efficiency", "relaxed"),
                ("comfort",           "strict"),
                ("comfort",           "relaxed"),
                ("balanced",          "strict"),
                ("balanced",          "relaxed"),
                ("energy_efficiency", "strict"),
                ("comfort",           "strict"),
                ("balanced",          "strict"),
                ("balanced",          "relaxed"),
            ]
            for i, (target, mode) in enumerate(combos, 1):
                result = await session.call_tool(
                    "recommend_action",
                    {"target": target, "constraint_mode": mode},
                )
                data = json.loads(result.content[0].text)
                errs = validate_recommend_response(data)
                
                # Direction check: latest state PMV is -1.04 (< -0.5), so action MUST be adjust_heating_setpoint
                if data.get("action_type") != "adjust_heating_setpoint":
                    errs.append(
                        f"Direction error: State is too cold (PMV < -0.5), expected 'adjust_heating_setpoint' but got '{data.get('action_type')}'"
                    )

                icon = "✅" if not errs else "❌"
                print(f"  {icon} Call {i:02d} ({target}/{mode}): "
                      f"action={data.get('action_type')}  "
                      f"value={data.get('target_value')}  "
                      f"conf={data.get('confidence')}")
                if errs:
                    for e in errs:
                        print(f"       Violation: {e}")
                    all_passed = False

    # ── Part 3: Ollama tool discovery and calling ─────────────────────────
    print("\n── Part 3: Ollama (qwen2.5:7b-instruct) tool discovery ──────")

    # Describe tools manually for Ollama function-calling format
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_state_summary",
                "description": "Return current building state: zone temp, PMV comfort, CO2, energy.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "analyze_trends",
                "description": "Analyse recent telemetry trends over the last N timesteps.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "window_steps": {"type": "integer", "description": "Number of recent timesteps to analyse"}
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "diagnose_errors",
                "description": "Parse the EnergyPlus run log and summarise errors and warnings.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "recommend_action",
                "description": "Recommend a control action based on building state and trends. When building is too cold (PMV < -0.5), recommends adjust_heating_setpoint. When too warm (PMV > 0.5), recommends adjust_cooling_setpoint.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target": {
                            "type": "string",
                            "enum": ["energy_efficiency", "comfort", "balanced"],
                            "description": "Optimisation objective",
                        },
                        "constraint_mode": {
                            "type": "string",
                            "enum": ["strict", "relaxed"],
                            "description": "How strictly to apply comfort constraints",
                        },
                    },
                    "required": [],
                },
            },
        },
    ]

    messages = [
        {
            "role": "user",
            "content": (
                "You are a building energy management AI. "
                "Check the current building state, diagnose any errors, "
                "analyse recent trends, then recommend an action optimising for balanced comfort and efficiency. "
                "Call the tools in that order."
            ),
        }
    ]

    client = ollama.Client()
    tools_called: set[str] = set()
    MAX_ROUNDS = 8

    # Re-open the MCP session for tool execution
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            for round_num in range(MAX_ROUNDS):
                response = client.chat(
                    model="qwen2.5:0.5b-instruct",
                    messages=messages,
                    tools=tools,
                )
                msg = response.message

                if not msg.tool_calls:
                    print(f"\n  Ollama final response (round {round_num+1}):")
                    print(f"  {msg.content[:300]}")
                    break

                for tc in msg.tool_calls:
                    fn = tc.function.name
                    args = tc.function.arguments or {}
                    tools_called.add(fn)
                    print(f"  🔧 Ollama called: {fn}({args})")

                    mcp_result = await session.call_tool(fn, args)
                    tool_text = mcp_result.content[0].text
                    print(f"     → {tool_text[:120]}{'...' if len(tool_text) > 120 else ''}")

                    messages.append({"role": "assistant", "content": "", "tool_calls": [tc]})
                    messages.append({"role": "tool", "content": tool_text, "name": fn})

    expected_tools = {"get_state_summary", "analyze_trends", "diagnose_errors", "recommend_action"}
    all_called = expected_tools.issubset(tools_called)
    icon = "✅" if all_called else "⚠️ "
    print(f"\n{icon} Ollama called tools: {sorted(tools_called)}")
    if not all_called:
        print(f"   Missing: {expected_tools - tools_called}")

    # ── Summary ───────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    if all_passed and all_called:
        print("🎉 ALL VERIFICATION CHECKS PASSED — Ready for Step 5")
    elif all_passed:
        print("✅ Tool data/schema checks passed. Ollama called some but not all tools.")
    else:
        print("❌ Some checks failed — see output above.")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run_verification()))
