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

Broken plugins are isolated: they log a warning and never crash the agent.
"""

import importlib.util
import sys
from pathlib import Path
from typing import Callable, Dict, List, Tuple

from rex.config import PLUGINS_DIR, load_config, normalize_config
from rex.logging_setup import log


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
    """Load enabled plugin tools. Returns {plugin_name: {"tools": [...]}}."""
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
            loaded[plugin_name] = {"tools": tools}
        else:
            log.warning("plugin tanpa tool valid name=%s", plugin_name)
    return loaded


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
    """Map tool name -> handler for every loaded plugin tool."""
    registry: Dict[str, Callable] = {}
    for plugin in load_plugins().values():
        for tool in plugin["tools"]:
            registry[tool["name"]] = tool["handler"]
    return registry


def effective_tool_definitions() -> List[dict]:
    """Built-in tool schemas plus plugin tool schemas."""
    from rex.tools import TOOL_DEFINITIONS
    return list(TOOL_DEFINITIONS) + plugin_tool_definitions()


def effective_tool_registry() -> Dict[str, Callable]:
    """Built-in tool handlers plus plugin tool handlers."""
    from rex.tools import TOOL_REGISTRY
    return {**TOOL_REGISTRY, **plugin_registry()}