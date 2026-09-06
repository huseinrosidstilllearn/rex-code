"""Self-check hook system (rex/hooks.py). Run: python test_hooks.py"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rex import hooks as hooks_mod
from rex.hooks import (
    apply_hooks,
    load_hooks,
    run_post_tool_use,
    run_pre_tool_use,
    _matching,
)


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


def write_hooks(tmp_dir: Path, data) -> Path:
    path = Path(tmp_dir) / "hooks.json"
    path.write_text(json.dumps(data) if isinstance(data, dict) else str(data), encoding="utf-8")
    return path


def fake_execute(code, out=""):
    return lambda hook, payload: (code, out)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        # ── 1. load_hooks: missing / broken / wrong shape → no hooks ────
        check("missing file -> empty", load_hooks(tmp_dir) == {"PreToolUse": [], "PostToolUse": []})
        broken = write_hooks(tmp_dir, "{not json")
        with patch("rex.hooks.hooks_file", return_value=broken):
            check("broken json -> empty", load_hooks() == {"PreToolUse": [], "PostToolUse": []})
        bad_shape = write_hooks(tmp_dir, ["PreToolUse"])
        with patch("rex.hooks.hooks_file", return_value=bad_shape):
            check("wrong shape -> empty", load_hooks() == {"PreToolUse": [], "PostToolUse": []})

        # ── 2. entry normalization ──────────────────────────────────────
        data = {
            "hooks": {
                "PreToolUse": [
                    {"matcher": "run_command", "command": "python g.py", "timeout_sec": 999},
                    {"command": "  "},
                    "not-a-dict",
                    {"matcher": "x", "command": "ok.py", "timeout_sec": 0},
                    {"command": "fine.py"},
                ],
                "PostToolUse": "not-a-list",
            }
        }
        path = write_hooks(tmp_dir, data)
        with patch("rex.hooks.hooks_file", return_value=path):
            hooks = load_hooks()
        check("valid entries kept", len(hooks["PreToolUse"]) == 3)
        check("timeout clamped high", hooks["PreToolUse"][0]["timeout_sec"] == 60)
        check("timeout clamped low", hooks["PreToolUse"][1]["timeout_sec"] == 1)
        check("matcher defaults to all", hooks["PreToolUse"][2]["matcher"] == ".*")
        check("post event wrong type -> none", hooks["PostToolUse"] == [])

        many = {"hooks": {"PreToolUse": [{"command": f"c{i}.py"} for i in range(30)]}}
        path = write_hooks(tmp_dir, many)
        with patch("rex.hooks.hooks_file", return_value=path):
            check("hook count capped", len(load_hooks()["PreToolUse"]) == 16)

        # ── 3. matcher semantics ────────────────────────────────────────
        check("matcher fullmatch", _matching({"matcher": "run_command"}, "run_command"))
        check("matcher rejects prefix", not _matching({"matcher": "run_command"}, "run_command_extra"))
        check("matcher alternation", _matching({"matcher": "a|b"}, "b"))
        check("invalid regex never matches", not _matching({"matcher": "(unclosed"}, "a"))

        # ── 4. PreToolUse decisions ─────────────────────────────────────
        with patch("rex.hooks.load_hooks", return_value={"PreToolUse": [], "PostToolUse": []}):
            check("no hooks -> allow", run_pre_tool_use("run_command", {}) is None)

        pre_ok = {"PreToolUse": [{"matcher": ".*", "command": "x"}], "PostToolUse": []}
        with patch("rex.hooks.load_hooks", return_value=pre_ok), \
             patch("rex.hooks._execute", fake_execute(0, "all good")):
            check("exit 0 -> allow", run_pre_tool_use("run_command", {}) is None)

        with patch("rex.hooks.load_hooks", return_value=pre_ok), \
             patch("rex.hooks._execute", fake_execute(2, "no rm -rf today")):
            check("exit 2 -> deny with reason", run_pre_tool_use("run_command", {}) == "no rm -rf today")

        with patch("rex.hooks.load_hooks", return_value=pre_ok), \
             patch("rex.hooks._execute", fake_execute(2, "")):
            check("exit 2 no stdout -> placeholder", "(tanpa pesan)" in run_pre_tool_use("run_command", {}))

        with patch("rex.hooks.load_hooks", return_value=pre_ok), \
             patch("rex.hooks._execute", fake_execute(1, "warning text")):
            check("exit 1 -> non-blocking", run_pre_tool_use("run_command", {}) is None)

        with patch("rex.hooks.load_hooks", return_value=pre_ok), \
             patch("rex.hooks._execute", fake_execute(124, "")):
            check("timeout -> non-blocking", run_pre_tool_use("run_command", {}) is None)

        matcher_hook = {"PreToolUse": [{"matcher": "write_file", "command": "x"}], "PostToolUse": []}
        with patch("rex.hooks.load_hooks", return_value=matcher_hook), \
             patch("rex.hooks._execute", MagicMock(return_value=(2, "denied"))) as ex:
            check("matcher filters other tools", run_pre_tool_use("list_dir", {}) is None)
            check("matcher hits target", run_pre_tool_use("write_file", {}) == "denied")
            check("hook ran once for hit", ex.call_count == 1)

        # ── 5. PostToolUse feedback ─────────────────────────────────────
        post_ok = {"PreToolUse": [], "PostToolUse": [{"matcher": ".*", "command": "fmt"}]}
        with patch("rex.hooks.load_hooks", return_value=post_ok), \
             patch("rex.hooks._execute", fake_execute(0, "auto-formatted")):
            check("post feedback returned", run_post_tool_use("edit_file", {}, "ok") == "auto-formatted")
        with patch("rex.hooks.load_hooks", return_value=post_ok), \
             patch("rex.hooks._execute", fake_execute(0, "")):
            check("post silent -> None", run_post_tool_use("edit_file", {}, "ok") is None)
        with patch("rex.hooks.load_hooks", return_value=post_ok), \
             patch("rex.hooks._execute", fake_execute(3, "boom")):
            check("post failure dropped", run_post_tool_use("edit_file", {}, "ok") is None)

        # ── 6. payload passed on stdin ──────────────────────────────────
        captured = {}
        def recording_execute(hook, payload):
            captured.update(payload)
            return (0, "")
        big = "x" * 5000
        with patch("rex.hooks.load_hooks", return_value=post_ok), \
             patch("rex.hooks._execute", recording_execute):
            run_post_tool_use("write_file", {"path": "a.txt"}, big)
        check("payload carries tool+args", captured.get("tool") == "write_file" and captured["args"] == {"path": "a.txt"})
        check("payload result truncated", len(captured.get("result", "")) == 4000)

        # ── 7. real subprocess wiring (echo + exit code) ────────────────
        from rex.shell import is_windows
        deny_cmd = "Write-Output 'blocked!'; exit 2" if is_windows() else "echo 'blocked!'; exit 2"
        real_hook = {"matcher": ".*", "command": deny_cmd, "timeout_sec": 10}
        with patch("rex.hooks.load_hooks", return_value={"PreToolUse": [real_hook], "PostToolUse": []}):
            check("real subprocess deny", run_pre_tool_use("run_command", {}) == "blocked!")

        fmt_cmd = "echo formatted" if not is_windows() else "Write-Output 'formatted'"
        post_hook = {"matcher": ".*", "command": fmt_cmd, "timeout_sec": 10}
        with patch("rex.hooks.load_hooks", return_value={"PreToolUse": [], "PostToolUse": [post_hook]}):
            check("real subprocess feedback", run_post_tool_use("edit_file", {}, "x") == "formatted")

        # ── 8. apply_hooks wrapping ─────────────────────────────────────
        calls = []
        def tool_fn(**kwargs):
            calls.append(kwargs)
            return "tool ran"

        with patch("rex.hooks.load_hooks", return_value={"PreToolUse": [], "PostToolUse": []}):
            registry = apply_hooks({"list_dir": tool_fn})
            check("no hooks -> registry untouched", registry["list_dir"] is tool_fn)

        deny_all = {"PreToolUse": [{"matcher": ".*", "command": "guard"}], "PostToolUse": []}
        with patch("rex.hooks.load_hooks", return_value=deny_all), \
             patch("rex.hooks._execute", fake_execute(2, "forbidden")):
            wrapped = apply_hooks({"list_dir": tool_fn})["list_dir"]
            out = wrapped(path=".")
            check("deny short-circuits tool", "DIBLOKIR HOOK" in out and "forbidden" in out)
            check("underlying func never ran", calls == [])

        allow_all = {"PreToolUse": [{"matcher": ".*", "command": "guard"}], "PostToolUse": [{"matcher": ".*", "command": "fmt"}]}
        with patch("rex.hooks.load_hooks", return_value=allow_all), \
             patch("rex.hooks._execute", side_effect=[(0, ""), (0, "formatted")]) as ex:
            wrapped = apply_hooks({"list_dir": tool_fn})["list_dir"]
            out = wrapped(path=".")
            check("allow runs tool", out == "tool ran\n\n[hook PostToolUse] formatted")
            check("pre+post both fired", ex.call_count == 2)

        def broken_fn(**kwargs):
            raise ValueError("kaput")
        with patch("rex.hooks.load_hooks", return_value=allow_all), \
             patch("rex.hooks._execute", side_effect=[(0, ""), (0, "seen")]):
            wrapped = apply_hooks({"list_dir": broken_fn})["list_dir"]
            out = wrapped()
            check("tool exception still hooked", "kaput" in out and "seen" in out)

        # ── 9. integration: effective_tool_registry + agent round ──────
        from rex.plugins import effective_tool_registry

        with patch("rex.hooks.load_hooks", return_value=deny_all), \
             patch("rex.hooks._execute", fake_execute(2, "no dirs today")):
            reg = effective_tool_registry()
            check("effective registry hooked", "DIBLOKIR HOOK" in reg["list_dir"](path="."))

        import rex.core as core_mod
        from rex.core import RexAgent
        from rex.providers.base import LLMResponse

        class ToolThenDone:
            def __init__(self):
                self.n = 0

            def chat(self, messages, system_prompt, tools=None):
                self.n += 1
                if self.n == 1:
                    return LLMResponse(content="", tool_calls=[{"name": "list_dir", "args": {"path": "."}}])
                tool_msg = [m for m in messages if m.get("role") == "tool"][-1]
                return LLMResponse(content=f"TOOL SAW: {tool_msg['content'][:60]}")

        with tempfile.TemporaryDirectory() as sess_tmp:
            from rex.sessions import SessionStore
            store = SessionStore(Path(sess_tmp))
            agent = RexAgent()
            events = []
            with patch.object(core_mod, "get_llm_provider_with_fallback", return_value=(ToolThenDone(), [("gemini", "m1")])), \
                 patch.object(core_mod, "build_context_prefix", return_value=""), \
                 patch("rex.core.maybe_compact", return_value=(None, False)), \
                 patch("rex.core.load_config", return_value={"max_history_messages": 40, "stream_enabled": False, "max_steps": 5, "anti_slop_enabled": False}), \
                 patch("rex.core.session_store", store), \
                 patch("rex.hooks.load_hooks", return_value=deny_all), \
                 patch("rex.hooks._execute", fake_execute(2, "no dirs today")):
                out = agent.run("lihat direktori", on_step=events.append)
            check("agent tool blocked by hook", "DIBLOKIR HOOK (PreToolUse): no dirs today" in out)

    print("\nAll hook checks PASS")


if __name__ == "__main__":
    main()
