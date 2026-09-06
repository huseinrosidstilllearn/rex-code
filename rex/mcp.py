"""
rex.mcp
=======
Minimal Model Context Protocol (MCP) client over **stdio** and **HTTP**.

Speaks JSON-RPC 2.0 with an MCP server:
  initialize -> notifications/initialized -> tools/list -> tools/call

- stdio transport: a server subprocess (command + args)
- HTTP transport (streamable-http style): POST JSON-RPC to a URL; the
  Mcp-Session-Id response header is honored when the server issues one

Exposed tools are merged into the agent tool registry as
``mcp_<server>_<tool>`` using the same plugin mechanism as local plugins.
A broken server never breaks the agent: its tools are simply not exposed.

Config (config.json -> "mcp"):

    "mcp": {
        "enabled": true,
        "servers": {
            "files": {"command": "python", "args": ["path/to/server.py"], "env": {}}
        }
    }
"""

from __future__ import annotations

import json
import subprocess
import threading
from typing import Any, Dict, List, Optional

import rex

JSONRPC_VERSION = "2.0"
PROTOCOL_VERSION = "2024-11-05"
REQUEST_TIMEOUT = 30
MAX_TOOL_RESULT_CHARS = 8000

_lock = threading.Lock()
_servers: Dict[str, "_ServerProcess"] = {}


class MCPError(Exception):
    pass


class _HttpServer:
    """HTTP (streamable) MCP transport: JSON-RPC POSTs to a single URL."""

    def __init__(self, name: str, url: str, headers: Optional[Dict[str, str]] = None):
        self.name = name
        self.url = url
        self.headers = headers or {}
        self.session_id: Optional[str] = None
        self._initialized = False
        self.next_id = 1

    def _post(self, payload: Dict[str, Any], expect_response: bool = True) -> Dict[str, Any]:
        import httpx
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **self.headers,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        try:
            response = httpx.post(self.url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
        except Exception as exc:
            raise MCPError(f"server '{self.name}' request failed: {exc}") from exc
        sid = response.headers.get("mcp-session-id")
        if sid:
            self.session_id = sid
        if response.status_code >= 400:
            raise MCPError(f"server '{self.name}' HTTP {response.status_code}")
        if not expect_response:
            return {}
        body = response.text
        if not body or not body.strip():
            return {}  # 202 Accepted style
        # Streamable responses may come back as SSE; extract the data line.
        if body.lstrip().startswith("event:") or "\ndata:" in body or body.lstrip().startswith("data:"):
            for line in body.splitlines():
                if line.startswith("data:"):
                    try:
                        return json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
            raise MCPError(f"server '{self.name}': no data in SSE response")
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise MCPError(f"server '{self.name}' returned invalid JSON") from exc

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        request_id = self.next_id
        self.next_id += 1
        result = self._post({
            "jsonrpc": JSONRPC_VERSION, "id": request_id, "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                "clientInfo": {"name": "rex-code", "version": rex.__version__},
            },
        })
        if "error" in result:
            raise MCPError(f"initialize error: {result['error']}")
        self.notify("notifications/initialized")
        self._initialized = True

    def request(self, method: str, params: Optional[Dict] = None, timeout: float = REQUEST_TIMEOUT) -> Dict[str, Any]:
        self._ensure_initialized()
        request_id = self.next_id
        self.next_id += 1
        result = self._post({"jsonrpc": JSONRPC_VERSION, "id": request_id, "method": method, "params": params or {}})
        # Some streamable servers omit the echoed id; the POST response to our
        # own request is authoritative, so only transport/JSON-RPC errors
        # and missing results are fatal.
        if "error" in result:
            raise MCPError(f"{method} error: {result['error']}")
        if "result" not in result and result:
            raise MCPError(f"{method}: unexpected response shape")
        return result.get("result") or {}

    def notify(self, method: str, params: Optional[Dict] = None) -> None:
        self._post({"jsonrpc": JSONRPC_VERSION, "method": method, "params": params or {}}, expect_response=False)

    def close(self) -> None:
        pass


class _ServerProcess:
    """One stdio MCP server subprocess with sequenced request ids."""

    def __init__(self, name: str, command: List[str], env: Optional[Dict[str, str]] = None):
        self.name = name
        self.command = command
        self.env = env or {}
        self.process: Optional[subprocess.Popen] = None
        self.next_id = 1

    def start(self) -> None:
        if self.process and self.process.poll() is None:
            return
        import os
        merged_env = os.environ.copy()
        merged_env.update(self.env)
        try:
            self.process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=merged_env,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except Exception as exc:
            raise MCPError(f"server '{self.name}' failed to start: {exc}") from exc

    def _send(self, payload: Dict[str, Any]) -> None:
        if not self.process or self.process.poll() is not None:
            raise MCPError(f"server '{self.name}' is not running")
        try:
            self.process.stdin.write(json.dumps(payload) + "\n")
            self.process.stdin.flush()
        except Exception as exc:
            raise MCPError(f"server '{self.name}' write failed: {exc}") from exc

    def _receive(self) -> Optional[Dict[str, Any]]:
        if not self.process or not self.process.stdout:
            raise MCPError(f"server '{self.name}' has no stdout")
        line = self.process.stdout.readline()
        if not line:
            return None
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return None

    def request(self, method: str, params: Optional[Dict] = None, timeout: float = REQUEST_TIMEOUT) -> Dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        self._send({"jsonrpc": JSONRPC_VERSION, "id": request_id, "method": method, "params": params or {}})
        import time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = self._receive()
            if message is None:
                continue
            if message.get("id") == request_id:
                if "error" in message:
                    raise MCPError(f"{method} error: {message['error']}")
                return message.get("result") or {}
        raise MCPError(f"{method} timed out after {timeout}s")

    def notify(self, method: str, params: Optional[Dict] = None) -> None:
        self._send({"jsonrpc": JSONRPC_VERSION, "method": method, "params": params or {}})

    def close(self) -> None:
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
            except Exception:
                pass
        self.process = None


def _mcp_section(cfg: dict) -> dict:
    """Accept either a full config (with an "mcp" key) or the mcp section itself."""
    if isinstance(cfg, dict) and isinstance(cfg.get("mcp"), dict):
        return cfg["mcp"]
    return cfg if isinstance(cfg, dict) else {}


def _get_server(name: str, cfg: Optional[dict] = None):
    with _lock:
        existing = _servers.get(name)
        if existing is not None:
            if isinstance(existing, _HttpServer):
                return existing  # stateless across calls; initialize memoized
            if existing.process and existing.process.poll() is None:
                return existing
        if cfg is None:
            from rex.config import load_config
            cfg = load_config()
        server_cfg = (_mcp_section(cfg).get("servers") or {}).get(name)
        if not isinstance(server_cfg, dict):
            raise MCPError(f"unknown MCP server '{name}'")
        if server_cfg.get("url"):
            server = _HttpServer(name, str(server_cfg["url"]), server_cfg.get("headers"))
            _servers[name] = server
            return server
        if not server_cfg.get("command"):
            raise MCPError(f"unknown MCP server '{name}'")
        command = [str(server_cfg["command"])] + [str(a) for a in server_cfg.get("args") or []]
        process = _ServerProcess(name, command, server_cfg.get("env"))
        process.start()
        result = process.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "rex-code", "version": "0.1.0"},
        }, timeout=10)
        _ = result  # server info unused; success is enough
        process.notify("notifications/initialized")
        _servers[name] = process
        return process


def close_all() -> None:
    with _lock:
        for process in _servers.values():
            process.close()
        _servers.clear()


# ── Tools surface ────────────────────────────────────────────────────

def list_server_tools(name: str, cfg: Optional[dict] = None) -> List[Dict[str, Any]]:
    """tools/list for one server. Raises MCPError on failure."""
    server = _get_server(name, cfg)
    result = server.request("tools/list", {})
    tools = result.get("tools")
    return tools if isinstance(tools, list) else []


def call_server_tool(name: str, tool: str, arguments: Dict[str, Any], cfg: Optional[dict] = None) -> str:
    """tools/call for one server. Returns text content of the result."""
    server = _get_server(name, cfg)
    result = server.request("tools/call", {"name": tool, "arguments": arguments or {}})
    if result.get("isError"):
        content = result.get("content") or []
        text = " ".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
        return f"Error dari server MCP '{name}': {text[:MAX_TOOL_RESULT_CHARS]}"
    blocks = []
    for part in result.get("content") or []:
        if isinstance(part, dict) and part.get("type") == "text":
            blocks.append(str(part.get("text", "")))
    text = "\n".join(blocks) if blocks else json.dumps(result, ensure_ascii=False)
    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = text[: MAX_TOOL_RESULT_CHARS - 14] + "\n...[dipotong]"
    return text


def _sanitize(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in name)


def mcp_tool_definitions(cfg: Optional[dict] = None) -> List[Dict[str, Any]]:
    """
    Tool definitions for every enabled server's tools, named
    mcp_<server>_<tool>. Broken servers are skipped silently.
    """
    if cfg is None:
        from rex.config import load_config
        cfg = load_config()
    mcp_cfg = _mcp_section(cfg)
    if not mcp_cfg.get("enabled", True):
        return []
    definitions: List[Dict[str, Any]] = []
    servers = mcp_cfg.get("servers") or {}
    for name, server_cfg in servers.items():
        if not isinstance(server_cfg, dict) or not (server_cfg.get("command") or server_cfg.get("url")):
            continue
        try:
            for tool in list_server_tools(name, cfg):
                tool_name = tool.get("name")
                if not tool_name:
                    continue
                definitions.append({
                    "name": f"mcp_{_sanitize(name)}_{_sanitize(str(tool_name))}",
                    "description": f"[MCP:{name}] {tool.get('description') or tool_name}",
                    "parameters": tool.get("inputSchema") or {"type": "object", "properties": {}},
                })
        except Exception:
            continue  # isolated: a broken server exposes nothing
    return definitions


def mcp_tool_registry(cfg: Optional[dict] = None) -> Dict[str, Any]:
    """Callables for mcp_tool_definitions(), closing over server+tool."""
    if cfg is None:
        from rex.config import load_config
        cfg = load_config()
    registry: Dict[str, Any] = {}
    mcp_cfg = _mcp_section(cfg)
    if not mcp_cfg.get("enabled", True):
        return registry
    servers = mcp_cfg.get("servers") or {}
    for name, server_cfg in servers.items():
        if not isinstance(server_cfg, dict) or not (server_cfg.get("command") or server_cfg.get("url")):
            continue
        try:
            for tool in list_server_tools(name, cfg):
                tool_name = tool.get("name")
                if not tool_name:
                    continue
                registry[f"mcp_{_sanitize(name)}_{_sanitize(str(tool_name))}"] = (
                    _make_handler(name, str(tool_name))
                )
        except Exception:
            continue
    return registry


def _make_handler(server_name: str, tool_name: str):
    def handler(**kwargs) -> str:
        return call_server_tool(server_name, tool_name, kwargs)

    handler.__name__ = f"mcp_{_sanitize(server_name)}_{_sanitize(tool_name)}"
    handler.__doc__ = f"Call MCP tool '{tool_name}' on server '{server_name}'."
    # Metadata consumed by the approval gate in rex.plugins (never trust the
    # sanitized registry key to recover the original names).
    handler._rex_server = server_name
    handler._rex_tool = tool_name
    return handler
