"""Self-check for the MCP stdio client (uses a real fixture server). Run: python test_mcp.py"""

import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rex.mcp as mcp
from rex.mcp import MCPError, call_server_tool, mcp_tool_definitions, mcp_tool_registry


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


def server_config():
    server_script = str(Path(__file__).resolve().parent / "mcp_fixture_server.py")
    return {
        "enabled": True,
        "servers": {"fixture": {"command": sys.executable, "args": [server_script]}},
    }


def main():
    mcp.close_all()
    try:
        cfg = server_config()

        # ── Tool discovery over stdio ─────────────────────────────────
        defs = mcp_tool_definitions(cfg)
        names = [d["name"] for d in defs]
        check("server tools discovered", "mcp_fixture_echo" in names and "mcp_fixture_add" in names)
        echo_def = next(d for d in defs if d["name"] == "mcp_fixture_echo")
        check("schema passed through", echo_def["parameters"].get("type") == "object")
        check("description prefixed", echo_def["description"].startswith("[MCP:fixture]"))

        # ── Tool call round-trip ──────────────────────────────────────
        registry = mcp_tool_registry(cfg)
        check("registry has handlers", "mcp_fixture_add" in registry)
        result = registry["mcp_fixture_add"](a=2, b=40)
        check("tools/call returns result", "42" in result)

        result = registry["mcp_fixture_echo"](text="halo rex")
        check("echo round-trip", "halo rex" in result)

        # ── Tool error surfaced as text, not exception ────────────────
        result = registry["mcp_fixture_fail"]()
        check("tool error returned as text", "Error dari server MCP" in result)

        # ── Disabled MCP exposes nothing ───────────────────────────────
        disabled = {"enabled": False, "servers": cfg["servers"]}
        check("disabled -> no definitions", mcp_tool_definitions(disabled) == [])
        check("disabled -> no registry", mcp_tool_registry(disabled) == {})

        # ── Broken server isolated (no crash, no tools) ───────────────
        broken = {"enabled": True, "servers": {
            "fixture": cfg["servers"]["fixture"],
            "bad": {"command": sys.executable, "args": ["-c", "import sys; sys.exit(1)"]},
        }}
        defs = mcp_tool_definitions(broken)
        check("broken server skipped", all(d["name"].startswith("mcp_fixture") for d in defs))
        check("good server still works", len(defs) >= 2)

        # ── Unknown server raises MCPError ────────────────────────────
        try:
            call_server_tool("nonexistent", "x", {}, cfg)
            check("unknown server raises", False)
        except MCPError:
            check("unknown server raises", True)

        # ── Config normalization ──────────────────────────────────────
        from rex.config import normalize_config
        norm = normalize_config({"mcp": {"servers": {
            "ok": {"command": "python", "args": ["s.py"], "env": {"K": "V"}},
            "nocmd": {"args": []},
            "notdict": "oops",
        }}})
        servers = norm["mcp"]["servers"]
        check("normalize keeps valid server", "ok" in servers and servers["ok"]["command"] == "python")
        check("normalize drops invalid", "nocmd" not in servers and "notdict" not in servers)
    finally:
        mcp.close_all()

    print("\nMCP checks PASS")


if __name__ == "__main__":
    main()
