"""Self-check /status aggregation (rex/status.py). Run: python test_status.py"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rex.status import collect_status, format_status


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


CFG = {
    "active_provider": "gemini",
    "active_model": "m1",
    "active_mode": "build",
    "token_budget": 25000,
    "mcp": {
        "enabled": True,
        "servers": {
            "fetch": {"command": "uvx", "args": ["mcp-server-fetch"]},
            "docs": {"url": "https://example.com/mcp"},
        },
    },
    "plugins": {"enabled": True, "list": ["external-one"]},
    "scheduler": {"enabled": True, "jobs": [
        {"id": "a", "cron": "0 22 * * *", "prompt": "p", "mode": "build", "enabled": True},
        {"id": "b", "cron": "0 23 * * *", "prompt": "p", "mode": "plan", "enabled": False},
    ]},
}


class FakeStoreList:
    @staticmethod
    def list():
        return [{"id": "x", "title": "kerja besar", "updated_at": "2026-09-06T10:00:00"}]


def names(results):
    return {item["name"] for item in results}


def main():
    patches = [
        patch("rex.review.load_config", return_value=dict(CFG)),
        patch("rex.review.normalize_config", side_effect=lambda c: c),
        patch("rex.plugins._discover_plugin_files", return_value=[Path("plugins/current_time.py")]),
        patch("rex.hooks.load_hooks", return_value={"PreToolUse": [{"matcher": ".*", "command": "g", "timeout_sec": 10}], "PostToolUse": []}),
        patch("rex.sessions.session_store", FakeStoreList),
    ]
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        data = collect_status()
    results = data["results"]
    by_name = {item["name"]: item for item in results}

    check("base doctor entries present", {"versi", "api_key", "provider"} <= names(results))
    check("config returned", data["config"]["token_budget"] == 25000)

    mcp = by_name["mcp"]
    check("mcp lists both servers", mcp["ok"] and "fetch[cmd]" in mcp["detail"] and "docs[http]" in mcp["detail"])
    check("plugins detail", by_name["plugins"]["ok"] and "current_time" in by_name["plugins"]["detail"] and "+1 di config" in by_name["plugins"]["detail"])
    check("hooks counted", by_name["hooks"]["ok"] and "PreToolUse: 1" in by_name["hooks"]["detail"] and "PostToolUse: 0" in by_name["hooks"]["detail"])
    check("scheduler counts", by_name["scheduler"]["ok"] and "2 job (1 aktif)" in by_name["scheduler"]["detail"])
    check("sessions summarized", by_name["sessions"]["ok"] and "kerja besar" in by_name["sessions"]["detail"])
    check("budget shown", by_name["budget"]["ok"] and "25,000" in by_name["budget"]["detail"])

    report = format_status()
    check("report renders marks", "✔" in report and "○" in report)
    check("report mentions sections", "mcp" in report and "plugins" in report and "hooks" in report)

    # Empty-config rendering: everything renders, nothing raises
    empty = {
        "active_provider": "gemini", "active_model": "m1", "active_mode": "plan",
        "mcp": {"enabled": False, "servers": {}},
        "plugins": {"enabled": True, "list": []},
        "scheduler": {"enabled": True, "jobs": []},
        "token_budget": 0,
    }
    with patch("rex.review.load_config", return_value=empty), \
         patch("rex.review.normalize_config", side_effect=lambda c: c), \
         patch("rex.plugins._discover_plugin_files", return_value=[]), \
         patch("rex.hooks.load_hooks", return_value={"PreToolUse": [], "PostToolUse": []}), \
         patch("rex.sessions.session_store", FakeStoreList):
        data = collect_status()
    by_name = {item["name"]: item for item in data["results"]}
    check("mcp disabled marked", not by_name["mcp"]["ok"] and "nonaktif" in by_name["mcp"]["detail"])
    check("no plugins marked", not by_name["plugins"]["ok"])
    check("no hooks marked", not by_name["hooks"]["ok"])
    check("unlimited budget marked", not by_name["budget"]["ok"] and "tidak dibatasi" in by_name["budget"]["detail"])

    # Subsystem explosion never breaks the report
    def boom():
        raise RuntimeError("kaput")
    with patch("rex.review.load_config", return_value=dict(empty)), \
         patch("rex.review.normalize_config", side_effect=lambda c: c), \
         patch("rex.plugins._discover_plugin_files", side_effect=boom), \
         patch("rex.hooks.load_hooks", side_effect=boom), \
         patch("rex.sessions.session_store", FakeStoreList):
        report = format_status()
    check("broken subsystems fail open", "Rex Status" in report and "plugins" in report)

    print("\nAll status checks PASS")


if __name__ == "__main__":
    main()
