"""Self-check agent foundations. Run: python test_foundations.py"""

import tempfile
from pathlib import Path
from unittest.mock import patch

from rex.providers.base import LLMResponse
from rex.sessions import SessionStore
from rex.tools import delete_file, edit_file, read_file, resolve_path, search_content


class ToolOnlyProvider:
    def chat(self, messages, system_prompt, tools=None):
        return LLMResponse(tool_calls=[{"id": "loop", "name": "list_dir", "args": {}}])


class AbortProvider:
    def __init__(self, agent_ref):
        self.agent_ref = agent_ref

    def chat(self, messages, system_prompt, tools=None):
        self.agent_ref[0].abort()
        return LLMResponse(tool_calls=[{"id": "stop", "name": "list_dir", "args": {}}])


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        raise AssertionError(name)


def main():
    from rex.config import PROJECT_ROOT, WORKFLOWS_DIR, WORKSPACE_DIR

    check("resolved paths stay in selected root", resolve_path("../config.json") is None)
    check("secret env file blocked", "DIBLOKIR" in read_file("../.env"))
    check("project config blocked", "DIBLOKIR" in read_file("../config.json"))
    check("session storage blocked", "DIBLOKIR" in read_file("../sessions/example.json"))

    sample = WORKSPACE_DIR / "foundation-large.txt"
    workflow = WORKFLOWS_DIR / "foundation-flow.json"
    try:
        sample.write_text("needle\n" + "x" * 300, encoding="utf-8")
        workflow.write_text('{"old": true}', encoding="utf-8")
        binary = WORKSPACE_DIR / "foundation.bin"
        binary.write_bytes(b"\x00\x01\x02")
        with patch("rex.tools.load_config", return_value={"file_read_max_chars": 100}):
            result = read_file("foundation-large.txt")
        check("large file read capped", len(result) <= 120 and "dipotong" in result.lower())
        check("binary file blocked", "biner" in read_file("foundation.bin"))
        check("content search reports line", "foundation-large.txt:1" in search_content("needle"))
        with patch("rex.tools.get_active_mode", return_value="build"):
            result = edit_file("workflows/foundation-flow.json", "true", "false")
            check("workflow edit supported", "Berhasil" in result and "false" in workflow.read_text(encoding="utf-8"))
            check("delete file supported", "Berhasil" in delete_file("foundation-large.txt") and not sample.exists())
        with patch("rex.tools.get_active_mode", return_value="plan"):
            check("plan mode blocks delete", "TIDAK DIIZINKAN" in delete_file("missing.txt"))
    finally:
        sample.unlink(missing_ok=True)
        workflow.unlink(missing_ok=True)
        (WORKSPACE_DIR / "foundation.bin").unlink(missing_ok=True)

    with tempfile.TemporaryDirectory() as temp_dir:
        store = SessionStore(Path(temp_dir))
        session_id = store.create("custom", "mock")["id"]
        with patch("rex.core.session_store", store), \
             patch("rex.core.get_llm_provider", return_value=ToolOnlyProvider()), \
             patch("rex.core.load_config", return_value={
                 "stream_enabled": False, "anti_slop_enabled": False,
                 "max_steps": 1, "max_history_messages": 40,
             }), \
             patch("rex.tools.get_active_mode", return_value="plan"):
            from rex.core import RexAgent
            response = RexAgent(session_id).run("loop")
        check("step limit returns useful response", "batas" in response.lower())
        check("step limit response persisted", store.load(session_id)["messages"][-1]["content"] == response)

        second_id = store.create("custom", "mock")["id"]
        holder = [None]
        with patch("rex.core.session_store", store), \
             patch("rex.core.get_llm_provider", side_effect=lambda: AbortProvider(holder)), \
             patch("rex.core.load_config", return_value={
                 "stream_enabled": False, "anti_slop_enabled": False,
                 "max_steps": 3, "max_history_messages": 40,
             }):
            holder[0] = RexAgent(second_id)
            response = holder[0].run("stop")
        check("abort stops before tool execution", "dibatalkan" in response.lower())

    check("project root unchanged", PROJECT_ROOT.exists())
    print("\nFoundation checks 14/14 PASS")


if __name__ == "__main__":
    main()