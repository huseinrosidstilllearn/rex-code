"""Self-check agent loop hygiene: wasted-repeat guard + step limits.
Suite #43. Run: python test_agentguard.py"""

import tempfile
from pathlib import Path
from unittest.mock import patch

from rex.providers.base import LLMResponse
from rex.sessions import SessionStore


class ScriptedProvider:
    """Router-style provider replaying a scripted sequence of responses."""

    def __init__(self, script):
        self.script = list(script)
        self.messages = []

    def chat(self, messages, system_prompt, tools=None):
        self.messages.append([dict(m) for m in messages])
        item = self.script.pop(0)
        if callable(item):
            return item()
        return item


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        raise AssertionError(name)


CFG = {
    "stream_enabled": False, "anti_slop_enabled": False,
    "max_steps": 25, "max_history_messages": 40,
}


def main():
    # ── 1. Guard: identical tool calls get replaced by a warning ──────
    from rex.agentguard import ToolCallGuard, activate_guard, deactivate_guard, active_guard

    g = ToolCallGuard(threshold=3)
    r1 = g.observe("read_file", {"path": "a.txt"})
    r2 = g.observe("read_file", {"path": "a.txt"})
    r3 = g.observe("read_file", {"path": "a.txt"})
    r4 = g.observe("read_file", {"path": "a.txt"})
    check("first two identical calls pass", r1 is None and r2 is None)
    check("third identical call warned", r3 is not None and "GUARD" in r3)
    check("counter resets -> next retry allowed", r4 is None)
    check("different args never warned", g.observe("read_file", {"path": "b.txt"}) is None)
    check("blocked counter tracked", g.blocked == 1)
    ge = ToolCallGuard(threshold=2)
    check("run_command exempt from guard", all(ge.observe("run_command", {"command": "pytest"}) is None for _ in range(5)))
    check("task_output exempt from guard", ge.observe("task_output", {"id": "t1"}) is None)

    # ── 2. ContextVar isolation for nested agents ─────────────────────
    outer, token = activate_guard()
    try:
        inner, inner_token = activate_guard()
        try:
            check("nested guard installed", active_guard() is inner and active_guard() is not outer)
        finally:
            deactivate_guard(inner_token)
        check("outer guard restored", active_guard() is outer)
    finally:
        deactivate_guard(token)
    check("no guard outside run()", active_guard() is None)

    # ── 3. Router loop consults the guard ────────────────────────────
    from rex.core import RexAgent
    import rex.core as core_mod

    calls = []

    def list_dir():
        calls.append(1)
        return "item"

    script = [
        {"id": "c1", "name": "probe_tool", "args": {}},
        {"id": "c2", "name": "probe_tool", "args": {}},
        {"id": "c3", "name": "probe_tool", "args": {}},
        {"id": "c4", "name": "probe_tool", "args": {}},
        LLMResponse(content="selesai"),
    ]
    script = [LLMResponse(tool_calls=[item]) if isinstance(item, dict) else item for item in script]
    provider = ScriptedProvider(script)

    def fake_effective_registry():
        return {"probe_tool": lambda: calls.append(1) or "hasil"}

    def fake_effective_definitions():
        return []

    with tempfile.TemporaryDirectory() as temp_dir:
        store = SessionStore(Path(temp_dir))
        sid = store.create("guard", "mock")["id"]
        with patch("rex.core.session_store", store), \
             patch("rex.core.get_llm_provider_with_fallback", return_value=(provider, [None])), \
             patch("rex.core.load_config", return_value=dict(CFG)), \
             patch("rex.core.build_context_prefix", return_value=""), \
             patch("rex.core.maybe_compact", return_value=(None, False)), \
             patch("rex.core.effective_tool_definitions", side_effect=fake_effective_definitions), \
             patch("rex.core.effective_tool_registry", side_effect=fake_effective_registry):
            agent = RexAgent(sid)
            out = agent.run("loop test")
        check("run completes after guard nudge", "selesai" in out)
        # Sequence: exec(1) exec(2) -> 3rd identical replaced by GUARD warning
        # -> 4th executes again (counter reset allows a legitimate retry,
        # e.g. re-reading after an edit). So exactly 3 real executions.
        check("guard blocked the wasted 3rd identical call", len(calls) == 3)
        check(
            "provider saw the guard warning",
            any(m.get("role") == "tool" and "GUARD" in str(m.get("content")) for m in agent.messages),
        )

    # ── 4. Step limit emits a step_limit StepEvent + useful summary ───
    events = []

    def on_step(event):
        events.append(event)

    loop_script = [LLMResponse(tool_calls=[{"id": "l", "name": "probe_tool", "args": {}}]) for _ in range(30)]
    loop_provider = ScriptedProvider(loop_script + [LLMResponse(content="tidak sampai sini")])

    with tempfile.TemporaryDirectory() as temp_dir:
        store = SessionStore(Path(temp_dir))
        sid = store.create("limit", "mock")["id"]
        with patch("rex.core.session_store", store), \
             patch("rex.core.get_llm_provider_with_fallback", return_value=(loop_provider, [None])), \
             patch("rex.core.load_config", return_value=dict(CFG, max_steps=3)), \
             patch("rex.core.build_context_prefix", return_value=""), \
             patch("rex.core.maybe_compact", return_value=(None, False)), \
             patch("rex.core.effective_tool_definitions", side_effect=fake_effective_definitions), \
             patch("rex.core.effective_tool_registry", side_effect=fake_effective_registry):
            out = RexAgent(sid).run("batas langkah", on_step=on_step)
        check("step limit returns useful response", "batas" in out.lower())
        kinds = [e.event_type for e in events]
        check("step_limit event fired", "step_limit" in kinds)
        check("step limit summary lists tools", "probe_tool" in out)

    # ── 5. edit_file fuzzy matching (whitespace-tolerant) ─────────────
    from rex.tools import _fuzzy_find

    check("fuzzy: exact match", _fuzzy_find("def foo():\n    return 1\n", "return 1") == (15, 23))
    check("fuzzy: indentation tolerant", _fuzzy_find("def foo():\n    return 1\n", "\t\treturn 1") is not None)
    check("fuzzy: trailing whitespace tolerant", _fuzzy_find("x = 1   \n", "x = 1") is not None)
    check("fuzzy: file without trailing newline", _fuzzy_find("a\nb\nc", "b\nc") == (2, 5))
    check("fuzzy: blank-line padding tolerant", _fuzzy_find("a\n\n\n  hello  \n", "\n\nhello\n") is not None)
    check("fuzzy: no match -> None", _fuzzy_find("aaa\nbbb", "zzz") is None)
    check("fuzzy: multiline window", _fuzzy_find("def a():\n    x = 1\n    y = 2\n\ndef b():\n", "x = 1\n    y = 2") == (13, 28))

    # ── 6. BUILD_MODE_PROMPT encodes the verification discipline ──────
    from rex.prompts import BUILD_MODE_PROMPT

    for keyword in ["Baca sebelum mengedit", "apply_patch", "Verifikasi sebelum klaim selesai", "todo_write"]:
        check(f"prompt mentions: {keyword}", keyword in BUILD_MODE_PROMPT)

    # ── 7. Agentic project memory (.rex/memory.md) ──────────────────────
    import tempfile as _tf
    from pathlib import Path as _P
    from rex.context_inject import agent_memory_path, append_agent_memory, read_agent_memory
    from rex.tools import memory_write
    from rex.config import WORKSPACE_DIR

    with _tf.TemporaryDirectory() as tmp:
        root = _P(tmp)
        ok1, _ = append_agent_memory("Konvensi: pesan commit Bahasa Indonesia", root)
        dup_ok, _ = append_agent_memory("Konvensi: pesan commit Bahasa Indonesia", root)
        blank_ok, _ = append_agent_memory("   ", root)
        check("memory append works", ok1 and read_agent_memory(root).startswith("Konvensi:"))
        check("memory dedups identical entries", not dup_ok)
        check("memory rejects empty entry", not blank_ok)
        check("memory lives in .rex/memory.md", agent_memory_path(root).relative_to(root).as_posix() == ".rex/memory.md")

    # memory_write redacts secrets before persisting
    from unittest.mock import patch as _patch
    with _tf.TemporaryDirectory() as tmp:
        with _patch("rex.context_inject.Path.cwd", lambda: _P(tmp)):
            result = memory_write("api_key=abcdefghijklmnopqrstuvwxyz123456")
            stored = read_agent_memory(_P(tmp))
            check("memory_write redacts secret", "REDACTED" in stored and "abcdefghijklmnopqrstuvwxyz" not in stored)

    # ── 8. RexWorker: build-mode gate + workspace-scoped writes ────────
    from rex.worker import RexWorker, is_worker_active
    from rex.tools import _is_sensitive
    import rex.worker as worker_mod
    from rex.config import get_active_mode as _get_mode

    check("no worker active by default", not is_worker_active())
    with _patch("rex.worker.get_active_mode", return_value="plan"), \
         _patch("rex.core.RexAgent") as _mock_agent:
        refused = RexWorker().run("tulis sesuatu")
        _mock_agent.assert_not_called()
    check("worker refused in plan mode", "DITOLAK" in refused or "Mode Build" in refused)

    # Scope enforcement: while a worker is active, paths outside workspace/
    # are treated as sensitive (blocked) by the tool layer.
    worker_mod._active_workers = 1
    try:
        check("worker: in-workspace path allowed", not _is_sensitive(WORKSPACE_DIR / "x.txt"))
        check("worker: project config blocked", _is_sensitive(WORKSPACE_DIR.parent / "config.json"))
        check("worker: workflows blocked", _is_sensitive(WORKSPACE_DIR.parent / "workflows" / "f.json"))
    finally:
        worker_mod._active_workers = 0
    check("worker scope lifted after run", not _is_sensitive(WORKSPACE_DIR / "x.txt"))

    print("\nAgentic guard checks ALL PASS")


if __name__ == "__main__":
    main()
