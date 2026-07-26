#!/usr/bin/env python3
"""
agent/mcp_server/test_client.py — Minimal MCP client smoke test.

Launches server.py as a subprocess over STDIO and calls each tool once,
printing results. Run from the mcp_server directory with the venv active.

Usage:
    .venv/bin/python test_client.py
"""

import asyncio
import sys
from pathlib import Path

# mcp client is in the same venv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_SCRIPT = Path(__file__).parent / "server.py"
PYTHON = sys.executable  # same venv python that's running this script


async def run_tests():
    server_params = StdioServerParameters(
        command=PYTHON,
        args=[str(SERVER_SCRIPT)],
    )

    print("=" * 60)
    print("  MCP Server Smoke Test")
    print("=" * 60)

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. List available tools
            tools_result = await session.list_tools()
            tool_names = [t.name for t in tools_result.tools]
            print(f"\n✅ Server started. Tools registered: {tool_names}")

            expected = {
                "get_state_summary",
                "analyze_trends",
                "diagnose_errors",
                "recommend_action",
            }
            missing = expected - set(tool_names)
            if missing:
                print(f"❌ Missing tools: {missing}")
                return 1

            # 2. Call each tool
            tests = [
                ("get_state_summary", {}),
                ("analyze_trends", {"window_steps": 12}),
                ("diagnose_errors", {}),
                ("recommend_action", {"target": "balanced", "constraint_mode": "strict"}),
            ]

            all_passed = True
            for tool_name, args in tests:
                result = await session.call_tool(tool_name, args)
                # result.content is a list of TextContent / other content blocks
                text = result.content[0].text if result.content else "(empty)"
                status_ok = '"status": "stub"' in text
                icon = "✅" if status_ok else "❌"
                print(f"\n{icon} {tool_name}({args})")
                print(f"   Response: {text[:180]}{'...' if len(text) > 180 else ''}")
                if not status_ok:
                    all_passed = False

            print("\n" + "=" * 60)
            if all_passed:
                print("🎉 All tools responded correctly — server is healthy.")
            else:
                print("❌ Some tools did not respond as expected.")
            return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run_tests()))
