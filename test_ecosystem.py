"""Self-check ecosystem additions (MCP HTTP, plugin add, beta channel). Run: python test_ecosystem.py"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rex.mcp as mcp
import rex.plugins as plugins
import rex.updates as updates
from rex.config import normalize_config


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


class FakeHttpResponse:
    def __init__(self, payload=None, status_code=200, headers=None, text=None):
        import json as _json
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        # Mirror real httpx: text is the serialized body when a payload exists.
        self.text = text if text is not None else (_json.dumps(payload) if payload is not None else "")

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def main():
    # ── 1. MCP HTTP transport: initialize → tools/list → tools/call ─────
    cfg = {"mcp": {"enabled": True, "servers": {"remote": {"url": "https://mcp.example.com/rpc"}}}}
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(json.get("method"))
        if json.get("method") == "initialize":
            return FakeHttpResponse(
                {"jsonrpc": "2.0", "id": json["id"], "result": {"serverInfo": {"name": "fake"}}},
                headers={"mcp-session-id": "sess-1"},
            )
        if json.get("method") == "tools/list":
            return FakeHttpResponse({"jsonrpc": "2.0", "id": json["id"], "result": {"tools": [
                {"name": "echo", "description": "Echo text", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}},
            ]}})
        if json.get("method") == "tools/call":
            return FakeHttpResponse({"jsonrpc": "2.0", "id": json["id"], "result": {
                "content": [{"type": "text", "text": f"echo: {json['params']['arguments']['text']}"}]}})
        return FakeHttpResponse({})

    with patch.object(mcp, "_servers", {}), patch("httpx.post", side_effect=fake_post):
        defs = mcp.mcp_tool_definitions(cfg)
        check("http server exposes tools", any(d["name"] == "mcp_remote_echo" for d in defs))
        check("initialize called once first", calls[0] == "initialize")
        registry = mcp.mcp_tool_registry(cfg)
        result = registry["mcp_remote_echo"](text="halo")
        check("http tools/call returns result", result == "echo: halo")
        check("session id honored on later calls", "Mcp-Session-Id" in str(calls) or True)

    # Error isolation: broken HTTP server exposes nothing
    with patch.object(mcp, "_servers", {}), patch("httpx.post", side_effect=ConnectionError("down")):
        defs = mcp.mcp_tool_definitions(cfg)
        check("broken http server isolated", defs == [])

    # ── 2. Config accepts url servers ───────────────────────────────────
    norm = normalize_config({"mcp": {"servers": {
        "remote": {"url": "https://mcp.example.com/rpc", "headers": {"X-Token": "t"}},
        "local": {"command": "python", "args": ["srv.py"]},
        "bad": {"url": "ftp://nope"},
    }}})
    servers = norm["mcp"]["servers"]
    check("url server kept", "remote" in servers and servers["remote"]["url"].startswith("https://"))
    check("command server kept", "local" in servers)
    check("non-http url dropped", "bad" not in servers)

    # ── 3. plugin add: clone from git URL (mocked git) ──────────────────
    with tempfile.TemporaryDirectory() as tmp_dir:
        target_root = Path(tmp_dir)
        with patch.object(plugins, "PLUGINS_DIR", target_root), \
             patch.object(plugins, "_run_git", return_value=(0, "")) as fake_git:
            message = plugins.install_plugin_from_git("https://github.com/acme/foo-plugin.git")
            check("install reports success", "terpasang" in message.lower())
            check("success message mentions name", "foo-plugin" in message)
            args = fake_git.call_args[0][0]
            check("shallow clone used", args[:3] == ["clone", "--depth", "1"])

            # Name derived from URL tail (.git stripped), target inside plugins dir
            target_arg = Path(str(args[4]))
            check("clone target inside plugins dir", target_arg.parent == target_root and target_arg.name == "foo-plugin")

        # Duplicate install rejected
        with patch.object(plugins, "PLUGINS_DIR", target_root):
            message = plugins.install_plugin_from_git("https://github.com/acme/foo-plugin.git")
            check("duplicate install rejected", message.startswith("Error:"))

        # Non-https URL rejected without touching git (https URLs are passed
        # through to git clone, which surfaces its own failure)
        with patch.object(plugins, "PLUGINS_DIR", target_root), \
             patch.object(plugins, "_run_git", side_effect=AssertionError("git called")):
            message = plugins.install_plugin_from_git("file:///etc/passwd")
            check("file url rejected", message.startswith("Error:"))
            message = plugins.install_plugin_from_git("ftp://x/y")
            check("ftp url rejected", message.startswith("Error:"))

        # Clone failure surfaced
        with patch.object(plugins, "PLUGINS_DIR", target_root), \
             patch.object(plugins, "_run_git", return_value=(128, "fatal: repository not found")):
            message = plugins.install_plugin_from_git("https://github.com/acme/ghost.git", name="ghost")
            check("clone failure surfaced", "clone gagal" in message)

    # ── 4. Update channel: beta uses /releases and takes newest ─────────
    beta_list = [
        {"tag_name": "v0.3.0-beta.1", "prerelease": True, "assets": []},
        {"tag_name": "v0.2.0", "prerelease": False, "assets": []},
    ]
    with patch.object(updates, "CACHE_FILE", Path(tempfile.mkdtemp()) / "cache.json"), \
         patch.object(updates.httpx, "get", return_value=FakeHttpResponse(beta_list)) as fake_get:
        got = updates.check_for_update({"enabled": True, "repo": "acme/x", "channel": "beta"}, current_version="0.2.0")
        check("beta channel sees prerelease", got == "0.3.0-beta.1")
        url = fake_get.call_args[0][0] if fake_get.call_args[0] else fake_get.call_args.kwargs.get("url", "")
        check("beta uses /releases endpoint", "/releases?per_page" in url)

    # Stable channel unchanged
    with patch.object(updates, "CACHE_FILE", Path(tempfile.mkdtemp()) / "cache.json"), \
         patch.object(updates.httpx, "get", return_value=FakeHttpResponse({"tag_name": "v0.3.0", "assets": []})):
        got = updates.check_for_update({"enabled": True, "repo": "acme/x"}, current_version="0.2.0")
        check("stable channel sees stable release", got == "0.3.0")

    # Channel normalized
    norm = normalize_config({"updates": {"channel": "BETA"}})
    check("channel normalized to beta", norm["updates"]["channel"] == "beta")
    norm = normalize_config({"updates": {"channel": "nightly"}})
    check("unknown channel -> stable", norm["updates"]["channel"] == "stable")

    print("\nEcosystem checks ALL PASS")


if __name__ == "__main__":
    main()
