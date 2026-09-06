"""
rex.plugins
Community-contributed tool plugins for Rex Code.

Plugins live in the `plugins/` directory at the project root:
  - plugins/<name>.py          (single-file plugin)
  - plugins/<name>/plugin.py   (plugin package)

A plugin module exposes PLUGIN_TOOLS — a list of tool descriptors with the
same "name"/"description"/"parameters" schema used by the built-in tools,
plus a callable "handler":

    PLUGIN_TOOLS = [
        {
            "name": "current_time",
            "description": "Mengembalikan waktu lokal saat ini.",
            "parameters": {
                "type": "object",
                "properties": {"timezone": {"type": "string", "description": "zona waktu IANA (opsional)"}},
                "required": [],
            },
            "handler": my_handler,   # callable; kwargs match parameters
        }
    ]

Alternatively a plugin may expose `register()` returning the same list.

Enable/disable via config.json:

    "plugins": {
        "enabled": true,
        "list": []        # empty = all; or ["current_time"] to allow-list
    }

Plugin API v2 — an optional ``plugin.toml`` manifest next to the entry
file (``<name>.toml`` for single-file, ``<name>/plugin.toml`` for
packages) declares metadata and explicit permissions::

    name = "my-plugin"
    version = "1.2.0"
    description = "What this plugin does"
    permissions = ["net", "fs"]   # net | shell | fs | env

``plugins.blocked_permissions`` in config fail-closes any plugin whose
manifest declares a blocked permission. Plugins without a manifest load
as legacy (permissions shown as "legacy"). ``/plugins`` renders the table.

Broken plugins are isolated: they log a warning and never crash the agent.
"""

import importlib.util
import re
import sys
from pathlib import Path
from typing import Callable, Dict, List, Tuple

from rex.approval import request_approval
from rex.config import PLUGINS_DIR, load_config, normalize_config
from rex.logging_setup import log
from rex.mcp import mcp_tool_definitions as _mcp_definitions
from rex.mcp import mcp_tool_registry as _mcp_registry


def _gate_external_tool(name: str, handler: Callable, action: str, meta: dict) -> Callable:
    """Wrap an external tool (MCP server / plugin) behind the approval gate.

    External code can do anything, so it is gated like built-in destructive
    tools (when approval is enabled; disabled = fail-open, unchanged).
    Errors are returned to the model with secret-looking values redacted.
    """

    def gated(**kwargs):
        summary_args = {"tool": name, **meta, "args": str(kwargs)[:120]}
        if not request_approval(action, _summarize(action, summary_args)):
            return f"DITOLAK PENGGUNA: eksekusi tool '{name}' tidak disetujui."
        try:
            return handler(**kwargs)
        except Exception as exc:
            return f"Error tool '{name}': {_redact(str(exc))[:400]}"

    gated.__name__ = f"gated_{action}_{name}"
    return gated


def _summarize(action: str, args: dict) -> str:
    from rex.approval import summarize_action
    return summarize_action(action, args)


def _redact(text: str) -> str:
    """Replace secret-looking substrings (keys/tokens) with <REDACTED>."""
    from rex.approval import SECRET_MARKERS
    pattern = re.compile(
        r"(?:" + "|".join(SECRET_MARKERS) + r")['\"\s:=]+[A-Za-z0-9_\-./+]{8,}",
        re.IGNORECASE,
    )
    return pattern.sub("<REDACTED>", text)


def _discover_plugin_files() -> List[Path]:
    """Return the plugin.py entry files found under plugins/ (sorted, stable)."""
    if not PLUGINS_DIR.is_dir():
        return []
    files: List[Path] = []
    for path in sorted(PLUGINS_DIR.iterdir()):
        if path.is_file() and path.suffix == ".py" and not path.name.startswith("_"):
            files.append(path)
        elif path.is_dir() and (path / "plugin.py").is_file():
            files.append(path / "plugin.py")
    return files


# ── Plugin API v2: plugin.toml manifest (name, version, permissions) ─

VALID_PERMISSIONS = ("net", "shell", "fs", "env")


def _manifest_path(plugin_file: Path) -> Path:
    """Single-file plugins: <name>.toml next to <name>.py; packages: plugin.toml."""
    if plugin_file.name == "plugin.py":
        return plugin_file.parent / "plugin.toml"
    return plugin_file.with_suffix(".toml")


def read_manifest(plugin_file: Path) -> Optional[Dict]:
    """
    Parse the optional ``plugin.toml`` manifest. Returns None when absent;
    a malformed manifest also returns None but is logged (plugin still
    loads as legacy without permissions).
    """
    path = _manifest_path(plugin_file)
    if not path.is_file():
        return None
    try:
        import tomllib
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        log.warning("plugin.toml tidak valid plugin=%s error=%s", plugin_file, exc)
        return None


def _manifest_meta(plugin_name: str, manifest: Optional[Dict]) -> Dict:
    """Normalized manifest metadata: {version, description, permissions, has_manifest}."""
    if not manifest:
        return {"version": "", "description": "", "permissions": [], "has_manifest": False}
    version = str(manifest.get("version") or "").strip()
    description = str(manifest.get("description") or "").strip()
    raw_permissions = manifest.get("permissions")
    permissions = []
    if isinstance(raw_permissions, list):
        valid = set(VALID_PERMISSIONS)
        permissions = [str(p).strip().lower() for p in raw_permissions
                       if isinstance(p, str) and str(p).strip().lower() in valid]
        unknown = {str(p).strip().lower() for p in raw_permissions
                   if isinstance(p, str) and str(p).strip().lower() not in valid}
        if unknown:
            log.warning("plugin manifest permission tidak dikenal plugin=%s: %s", plugin_name, ", ".join(sorted(unknown)))
    return {"version": version, "description": description, "permissions": permissions, "has_manifest": True}


def _blocked_by_permissions(meta: Dict, cfg: Dict) -> bool:
    """True when the manifest declares a permission the config blocks."""
    blocked = {str(p).strip().lower() for p in (cfg.get("plugins") or {}).get("blocked_permissions") or []}
    return bool(blocked and set(meta["permissions"]) & blocked)


def _plugin_name(plugin_file: Path) -> str:
    if plugin_file.name == "plugin.py":
        return plugin_file.parent.name
    return plugin_file.stem


def _load_plugin_module(plugin_file: Path):
    name = _plugin_name(plugin_file)
    module_name = f"rex_plugin_{name}"
    spec = importlib.util.spec_from_file_location(module_name, plugin_file)
    if spec is None or spec.loader is None:
        raise ImportError(f"Tidak dapat memuat {plugin_file}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _validate_tools(raw, plugin_name: str) -> List[dict]:
    if not isinstance(raw, (list, tuple)):
        log.warning("plugin tools invalid plugin=%s (bukan list)", plugin_name)
        return []
    valid: List[dict] = []
    for index, tool in enumerate(raw):
        if not isinstance(tool, dict):
            continue
        name = tool.get("name")
        handler = tool.get("handler")
        if not isinstance(name, str) or not name or not callable(handler):
            log.warning("plugin tool skipped plugin=%s index=%s (name/handler tidak valid)", plugin_name, index)
            continue
        parameters = tool.get("parameters")
        if not isinstance(parameters, dict):
            parameters = {"type": "object", "properties": {}, "required": []}
        properties = parameters.get("properties")
        required = parameters.get("required")
        if not isinstance(properties, dict) or not isinstance(required, list):
            log.warning("plugin tool skipped plugin=%s tool=%s (schema tidak valid)", plugin_name, name)
            continue
        if any(req not in properties for req in required):
            log.warning("plugin tool skipped plugin=%s tool=%s (required tidak cocok dengan properties)", plugin_name, name)
            continue
        valid.append({
            "name": name,
            "description": str(tool.get("description") or ""),
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": [str(req) for req in required],
            },
            "handler": handler,
            "plugin": plugin_name,
        })
    return valid


def load_plugins() -> Dict[str, dict]:
    """
    Load enabled plugin tools. Returns ``{plugin_name: {"tools", "version",
    "permissions", "has_manifest", "blocked"}}``.

    Plugins with a ``plugin.toml`` declaring a permission listed in
    ``config plugins.blocked_permissions`` are NOT loaded (fail-closed for
    that plugin); everything else behaves as before.
    """
    cfg = normalize_config(load_config())
    plugins_cfg = cfg.get("plugins") or {}
    if not plugins_cfg.get("enabled", True):
        return {}
    allowlist = {str(item).lower() for item in plugins_cfg.get("list") or [] if isinstance(item, str)}

    loaded: Dict[str, dict] = {}
    for plugin_file in _discover_plugin_files():
        plugin_name = _plugin_name(plugin_file)
        if allowlist and plugin_name.lower() not in allowlist:
            continue
        manifest = read_manifest(plugin_file)
        meta = _manifest_meta(plugin_name, manifest)
        if _blocked_by_permissions(meta, cfg):
            log.warning("plugin diblokir oleh blocked_permissions name=%s permissions=%s", plugin_name, meta["permissions"])
            loaded[plugin_name] = {**meta, "tools": [], "blocked": True}
            continue
        try:
            module = _load_plugin_module(plugin_file)
            raw = getattr(module, "PLUGIN_TOOLS", None)
            if raw is None:
                register = getattr(module, "register", None)
                raw = register() if callable(register) else None
        except Exception as exc:
            log.warning("plugin gagal dimuat name=%s error=%s", plugin_name, exc)
            continue
        tools = _validate_tools(raw, plugin_name)
        if tools:
            loaded[plugin_name] = {**meta, "tools": tools, "blocked": False}
        else:
            log.warning("plugin tanpa tool valid name=%s", plugin_name)
    return loaded


def format_plugins_table() -> str:
    """/plugins rendering: discovered plugins with version, permissions, status."""
    cfg = normalize_config(load_config())
    plugins_cfg = cfg.get("plugins") or {}
    if not plugins_cfg.get("enabled", True):
        return "(plugin system nonaktif — config plugins.enabled)"
    loaded = load_plugins()
    discovered = {_plugin_name(f): f for f in _discover_plugin_files()}
    if not discovered:
        return "(belum ada plugin — rex plugin add <git-url> atau taruh di plugins/)"
    allowlist = {str(item).lower() for item in plugins_cfg.get("list") or [] if isinstance(item, str)}
    lines = [f"{'Plugin':<20} {'Versi':<8} {'Izin':<16} {'Tool':>4}  Status", "-" * 76]
    for name in sorted(discovered):
        info = loaded.get(name)
        manifest_path = _manifest_path(discovered[name])
        has_manifest = manifest_path.is_file()
        version = (info or {}).get("version", "") or ("-")
        permissions = ", ".join((info or {}).get("permissions", [])) or ("-" if has_manifest else "legacy")
        if info is None:
            status = "nonaktif (allowlist)" if allowlist and name.lower() not in allowlist else "tanpa tool valid"
        elif info.get("blocked"):
            status = "DIBLOKIR (blocked_permissions)"
        else:
            status = "aktif"
        tool_count = len(info["tools"]) if info and info.get("tools") else 0
        lines.append(f"{name:<20} {version:<8} {permissions:<16} {tool_count:>4}  {status}")
    return "\n".join(lines)


def plugin_tool_definitions() -> List[dict]:
    """OpenAI-compatible schemas for every loaded plugin tool."""
    definitions: List[dict] = []
    for plugin in load_plugins().values():
        for tool in plugin["tools"]:
            definitions.append({
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["parameters"],
            })
    return definitions


def plugin_registry() -> Dict[str, Callable]:
    """Map tool name -> approval-gated handler for every loaded plugin tool."""
    registry: Dict[str, Callable] = {}
    for plugin in load_plugins().values():
        for tool in plugin["tools"]:
            registry[tool["name"]] = _gate_external_tool(
                tool["name"], tool["handler"], "plugin_tool", {"plugin": tool.get("plugin", "?")}
            )
    return registry


def _run_git(args: List[str], timeout: int = 120) -> Tuple[int, str]:
    """Run git in PLUGINS_DIR's parent (the data dir). Returns (code, output)."""
    import subprocess
    from rex.config import DATA_DIR
    try:
        result = subprocess.run(
            ["git", *args], cwd=str(DATA_DIR), capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
        )
        return result.returncode, (result.stdout or "") + (result.stderr or "")
    except Exception as exc:
        return 1, str(exc)


def install_plugin_from_git(url: str, name: Optional[str] = None) -> str:
    """
    Install a plugin from a git URL: shallow-clone into plugins/<name>.
    The plugin becomes active on the next tool listing (if it exposes
    valid PLUGIN_TOOLS / register()). Returns a human-readable result.
    """
    url = str(url or "").strip()
    if not url.startswith(("https://", "git@")):
        return "Error: hanya URL git https:// atau git@ yang didukung."
    if not name:
        tail = url.rstrip("/").rsplit("/", 1)[-1]
        name = tail[:-4] if tail.endswith(".git") else tail
    name = _sanitize_plugin_name(name or "")
    if not name or name.startswith("_"):
        return f"Error: nama plugin tidak valid: '{name}'"
    target = PLUGINS_DIR / name
    if target.exists():
        return f"Error: plugin '{name}' sudah ada di {target} — hapus dulu bila ingin mengganti."
    code, output = _run_git(["clone", "--depth", "1", url, str(target)])
    if code != 0:
        return f"Error: clone gagal: {output.strip()[:300]}"
    entry = target / "plugin.py"
    if not entry.is_file() and not (target / "__init__.py").is_file():
        # Not fatal: single-file layouts drop plugin.py at the root; anything
        # else still cloned, but warn that discovery may skip it.
        return f"Terpasang di {target} (perhatian: tidak ada plugin.py di root)."
    return f"Plugin '{name}' terpasang di {target} — aktif pada sesi berikutnya."


def _sanitize_plugin_name(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in name).strip("_")


def effective_tool_definitions() -> List[dict]:
    """Built-in tool schemas plus plugin and MCP tool schemas."""
    from rex.tools import TOOL_DEFINITIONS
    definitions = list(TOOL_DEFINITIONS) + plugin_tool_definitions()
    try:
        definitions = definitions + _mcp_definitions()
    except Exception:
        pass  # MCP must never break tool listing
    return definitions


def effective_tool_registry() -> Dict[str, Callable]:
    """Built-in tool handlers plus approval-gated plugin and MCP tool handlers."""
    from rex.tools import TOOL_REGISTRY
    registry = {**TOOL_REGISTRY, **plugin_registry()}
    try:
        for name, handler in _mcp_registry().items():
            server = getattr(handler, "_rex_server", "?")
            registry[name] = _gate_external_tool(
                getattr(handler, "_rex_tool", name), handler, "mcp_tool", {"server": server}
            )
    except Exception:
        pass  # MCP must never break tool execution
    try:
        from rex.hooks import apply_hooks
        registry = apply_hooks(registry)
    except Exception:
        pass  # hooks must never break tool execution
    return registry