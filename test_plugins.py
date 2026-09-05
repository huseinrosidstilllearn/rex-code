"""Self-check plugin system. Run: python test_plugins.py"""

import inspect
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rex.plugins import (
    effective_tool_definitions,
    effective_tool_registry,
    load_plugins,
    plugin_registry,
    plugin_tool_definitions,
)
from rex.providers.gemini import _build_wrapped_tool


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


def make_plugin(tmp: Path, name: str, content: str, package: bool = False):
    if package:
        folder = Path(tmp) / name
        folder.mkdir(exist_ok=True)
        target = folder / "plugin.py"
    else:
        target = Path(tmp) / f"{name}.py"
    target.write_text(content, encoding="utf-8")
    return target


def noop_load(cfg):
    return cfg


def main():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)

        weather = make_plugin(tmp, "weather", '''
def _weather(city: str):
    return f"Cuaca di {city}: cerah"

PLUGIN_TOOLS = [{
    "name": "weather_now",
    "description": "Cek cuaca.",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
    "handler": _weather,
}]
''')
        jira = make_plugin(tmp, "jira", '''
def register():
    def _issue(key: str):
        return f"Issue {key}"
    return [{
        "name": "jira_fetch",
        "description": "Ambil issue.",
        "parameters": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
        "handler": _issue,
    }]
''', package=True)
        broken = make_plugin(tmp, "broken", "raise RuntimeError('plugin meledak')\n")

        # 1. Discovery loads single-file + package plugins, register() supported
        with patch("rex.plugins._discover_plugin_files", return_value=[weather, jira]), \
             patch("rex.plugins.load_config", return_value={}), \
             patch("rex.plugins.normalize_config", side_effect=noop_load):
            loaded = load_plugins()
        check("single-file plugin loaded", "weather" in loaded)
        check("package plugin loaded via register()", "jira" in loaded)
        check("plugin tool names exposed", {t["name"] for p in loaded.values() for t in p["tools"]} == {"weather_now", "jira_fetch"})

        # 2. Broken plugin is isolated, others still load
        with patch("rex.plugins._discover_plugin_files", return_value=[weather, broken]), \
             patch("rex.plugins.load_config", return_value={}), \
             patch("rex.plugins.normalize_config", side_effect=noop_load):
            loaded = load_plugins()
        check("broken plugin isolated", "weather" in loaded and "broken" not in loaded)

        # 3. Config gate: disabled -> nothing loads
        with patch("rex.plugins._discover_plugin_files", return_value=[weather]), \
             patch("rex.plugins.load_config", return_value={"plugins": {"enabled": False}}), \
             patch("rex.plugins.normalize_config", side_effect=noop_load):
            loaded = load_plugins()
        check("disabled config blocks plugins", loaded == {})

        # 4. Allowlist limits which plugins load
        with patch("rex.plugins._discover_plugin_files", return_value=[weather, jira]), \
             patch("rex.plugins.load_config", return_value={"plugins": {"list": ["weather"]}}), \
             patch("rex.plugins.normalize_config", side_effect=noop_load):
            loaded = load_plugins()
        check("allowlist filters plugins", "weather" in loaded and "jira" not in loaded)

        # 5. Invalid tool schemas are skipped
        sloppy = make_plugin(tmp, "sloppy", '''
PLUGIN_TOOLS = [
    {"name": "no_handler"},
    {"name": "bad_required", "parameters": {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["missing"]}, "handler": lambda: "x"},
    {"name": "good_one", "parameters": {"type": "object", "properties": {"a": {"type": "string"}}, "required": []}, "handler": lambda: "ok"},
]
''')
        with patch("rex.plugins._discover_plugin_files", return_value=[sloppy]), \
             patch("rex.plugins.load_config", return_value={}), \
             patch("rex.plugins.normalize_config", side_effect=noop_load):
            loaded = load_plugins()
        names = {t["name"] for p in loaded.values() for t in p["tools"]}
        check("invalid schemas skipped", names == {"good_one"})

    # 6. effective_* merge built-ins with plugin tools
    fake_plugin = {
        "sample": {"tools": [{
            "name": "sample_tool",
            "description": "tool contoh",
            "parameters": {"type": "object", "properties": {}, "required": []},
            "handler": lambda: "hasil plugin",
        }]}
    }
    with patch("rex.plugins.load_plugins", return_value=fake_plugin):
        definitions = effective_tool_definitions()
        registry = effective_tool_registry()
    builtin_names = {"read_file", "write_file", "run_command", "git_publish"}
    check("built-ins preserved in definitions", builtin_names <= {d["name"] for d in definitions})
    check("plugin tool in definitions", "sample_tool" in {d["name"] for d in definitions})
    check("plugin handler in registry", "sample_tool" in registry and registry["sample_tool"]() == "hasil plugin")
    check("built-in handler in registry", "read_file" in registry)

    # 7. Gemini wrapper: signature from handler, callback, truncation
    def handler(city: str, unit: str = "c"):
        return f"{city}:{unit}"

    calls = []
    wrapped = _build_wrapped_tool("weather_now", handler, lambda name, args: calls.append((name, args)), 1000)
    sig = inspect.signature(wrapped)
    check("wrapper keeps required param", "city" in sig.parameters and sig.parameters["city"].default is inspect.Parameter.empty)
    check("wrapper keeps optional param", "unit" in sig.parameters and sig.parameters["unit"].default is None)
    check("wrapper executes handler", wrapped(city="Bandung") == "Bandung:c" and wrapped("Jakarta", "f") == "Jakarta:f")
    check("wrapper notifies callback", calls == [("weather_now", {"city": "Bandung"}), ("weather_now", {"city": "Jakarta", "unit": "f"})])

    long_handler = lambda: "x" * 1000
    wrapped_long = _build_wrapped_tool("long", long_handler, None, 50)
    check("wrapper truncates long output", "...[dipotong]" in wrapped_long())

    # 8. Integration: the shipped sample plugin loads and runs
    with patch("rex.plugins.load_config", return_value={}), \
         patch("rex.plugins.normalize_config", side_effect=noop_load):
        registry = plugin_registry()
    check("shipped current_time plugin discovered", "current_time" in registry)
    if "current_time" in registry:
        result = registry["current_time"](timezone="Asia/Jakarta")
        check("shipped plugin executes", "Asia/Jakarta" in result and "WIB" in result and ":" in result)
        check("plugin reports unknown timezone", "tidak dikenal" in registry["current_time"](timezone="Mars/Phobos"))

    print("\nPlugin checks 18/18 PASS")


if __name__ == "__main__":
    main()