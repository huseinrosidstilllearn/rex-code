"""Self-check shared ChatController (rex/app_controller.py). Run: python test_app_controller.py"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rex.app_controller import ChatController, msg


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


class FakeAgent:
    """Stands in for RexAgent: records run() calls, emits one done event."""

    instances = []

    def __init__(self, session_id=None):
        self.session_id = session_id
        self.run_calls = []
        self.abort_calls = 0
        self.usage = MagicMock()
        self.usage.format_summary.return_value = "total 5 token"
        FakeAgent.instances.append(self)

    def run(self, text, on_step=None):
        self.run_calls.append(text)
        return f"jawaban: {text}"

    def abort(self):
        self.abort_calls += 1


CFG = {
    "active_provider": "gemini",
    "active_model": "m1",
    "active_mode": "plan",
    "providers": {
        "gemini": {"name": "Gemini", "type": "gemini", "api_key_env": "GEMINI_API_KEY",
                   "model": "m1", "available_models": ["m1", "m2"]},
        "custom": {"name": "Custom", "type": "openai_compatible", "base_url": "http://x/v1",
                   "api_key_env": "CUSTOM_KEY", "model": "c1", "available_models": ["c1"]},
    },
}


def make_controller(tmp_sessions):
    """Controller with every external touch patched out."""
    store = tmp_sessions
    with patch("rex.app_controller.session_store", store), \
         patch("rex.app_controller.RexAgent", FakeAgent), \
         patch("rex.app_controller.get_active_provider_info", return_value=("gemini", {}, "m1")):
        return ChatController(auto_resume=False)


def main():
    import json
    from rex.sessions import SessionStore

    with tempfile.TemporaryDirectory() as tmp:
        store = SessionStore(Path(tmp) / "sessions")
        # Keep every agent/store touch fake for the whole suite — no network.
        patcher_store = patch("rex.app_controller.session_store", store)
        patcher_agent = patch("rex.app_controller.RexAgent", FakeAgent)
        patcher_info = patch("rex.app_controller.get_active_provider_info", return_value=("gemini", {}, "m1"))
        patcher_store.start()
        patcher_agent.start()
        patcher_info.start()
        controller = ChatController(auto_resume=False)

        # ── 1. lifecycle ────────────────────────────────────────────────
        check("controller starts with a session", bool(controller.session_id))
        check("agent built", controller.agent_ready())
        sid1 = controller.session_id
        changed = controller.new_session()
        check("new_session changes id", changed["type"] == "session_changed" and controller.session_id != sid1)
        check("old session closed", store.load(sid1)["status"] == "closed")

        missing = controller.resume_session("ffffffffffffffffffffffffffffffff")
        check("resume unknown -> error event", missing["type"] == "message" and missing["style"] == "error")

        sid2 = controller.session_id
        store.append(sid2, {"role": "user", "content": "halo"})
        check("delete active session -> fresh session", controller.delete_session(sid2)["type"] == "message" and controller.session_id != sid2)

        # ── 2. slash dispatch: modes ────────────────────────────────────
        with patch("rex.app_controller.set_active_mode") as setter, \
             patch("rex.app_controller.set_active_mode" if False else "rex.app_controller.load_config", return_value=dict(CFG)):
            events = controller.dispatch("/plan")
        check("/plan emits mode_changed", events[0] == {"type": "mode_changed", "mode": "PLAN"})
        setter.assert_called_with("plan")
        with patch("rex.app_controller.set_active_mode") as setter:
            events = controller.dispatch("/build")
        check("/build emits BUILD", events[0]["mode"] == "BUILD")

        check("unknown command -> error", "tidak dikenal" in controller.dispatch("/bogus")[0]["text"])

        # ── 3. /models data + switching ────────────────────────────────
        with patch("rex.app_controller.load_config", return_value=json.loads(json.dumps(CFG))), \
             patch("rex.app_controller.normalize_config", side_effect=lambda c: c), \
             patch("rex.app_controller.save_config") as saver, \
             patch("rex.app_controller._env_keys", return_value={}):
            with patch.dict("os.environ", {}, clear=True):
                events = controller.dispatch("/models")  # no keys in env -> has_key False
        providers_event = next(e for e in events if e["type"] == "providers")
        check("/models lists providers with key state", len(providers_event["items"]) == 2
              and providers_event["items"][0]["api_key_env"] == "GEMINI_API_KEY"
              and providers_event["items"][0]["has_key"] is False)

        with patch("rex.app_controller.load_config", return_value=json.loads(json.dumps(CFG))), \
             patch("rex.app_controller.normalize_config", side_effect=lambda c: c), \
             patch("rex.app_controller.save_config") as saver:
            events = controller.dispatch("/models custom c1")
        check("/models switch saves config", saver.called and "Provider aktif: custom" in events[0]["text"])

        with patch("rex.app_controller.load_config", return_value=json.loads(json.dumps(CFG))), \
             patch("rex.app_controller.normalize_config", side_effect=lambda c: c):
            check("/models bad provider -> error", "tidak dikenal" in controller.dispatch("/models ghost")[0]["text"])
            check("/models bad model -> error", "tidak ada" in controller.dispatch("/models gemini zz9")[0]["text"])

        # ── 4. /settings snapshot ──────────────────────────────────────
        with patch("rex.app_controller.load_config", return_value=json.loads(json.dumps(CFG))), \
             patch("rex.app_controller.normalize_config", side_effect=lambda c: c), \
             patch("rex.app_controller.get_active_provider_info", return_value=("gemini", {}, "m1")):
            events = controller.dispatch("/settings")
        data = events[0]["data"]
        check("/settings exposes providers + toggles", len(data["providers"]) == 2
              and data["token_budget"] == 0 and "anti_slop_enabled" in data)

        # ── 5. /cost + /commit flow ────────────────────────────────────
        controller.agent = FakeAgent(controller.session_id)  # deterministic meter
        events = controller.dispatch("/cost")
        check("/cost uses meter summary", "total 5 token" in events[0]["text"])

        with patch("rex.autogit.generate_commit_message", return_value="feat: x"), \
             patch("rex.autogit.commit_with_message", return_value="COMMITTED") as commit_fn:
            events = controller.dispatch("/commit")
            check("/commit proposes", "feat: x" in events[0]["text"] and "/commit yes" in events[0]["text"])
            events = controller.dispatch("/commit yes")
            check("/commit yes executes", commit_fn.called and "COMMITTED" in events[0]["text"])
            check("pending cleared", controller._pending_commit is None)

        # ── 6. sessions commands ───────────────────────────────────────
        sid_a = store.create("gemini", "m1")["id"]
        store.append(sid_a, {"role": "user", "content": "kerja A"})
        sid_b = store.create("gemini", "m1")["id"]
        store.append(sid_b, {"role": "user", "content": "kerja B"})
        events = controller.dispatch("/sessions")
        check("/sessions lists", "kerja A" in events[0]["text"])
        events = controller.dispatch("/resume 1")
        check("/resume <n> switches", any(e.get("type") == "session_changed" for e in events))
        check("unknown use -> error", "tidak ditemukan" in controller.dispatch("/use deadbeef")[0]["text"])
        check("empty delete -> hint", "Pakai" in controller.dispatch("/delete")[0]["text"])

        # ── 7. misc commands ───────────────────────────────────────────
        check("/files returns table", controller.dispatch("/files")[0]["type"] == "table")
        check("/anti-slop needs text", "Pakai" in controller.dispatch("/anti-slop")[0]["text"])
        check("/help items", any(e["type"] == "help" and len(e["items"]) > 20 for e in controller.dispatch("/help")))
        check("/exit quits", controller.dispatch("/exit") == [{"type": "quit"}])

        # ── 8. submit: plain text runs the agent thread ────────────────
        received = []
        controller.submit("buat fungsi hello", received.append)
        import time
        deadline = time.time() + 5
        while time.time() < deadline and not (received and received[-1].get("type") == "agent_state"
                                              and received[-1]["running"] is False):
            time.sleep(0.05)
        types = [e["type"] for e in received]
        check("run emits agent_state start/end", "agent_state" in types and received[-1]["running"] is False)
        check("run emits done with answer", any(e["type"] == "done" and "jawaban: buat fungsi hello" in e["text"] for e in received))
        check("agent received prompt", controller.agent.run_calls == ["buat fungsi hello"])

        # second submit while running is refused
        rejected = []
        controller._running = True
        controller.submit("dua", rejected.append)
        controller._running = False
        check("concurrent submit refused", any("masih memproses" in e.get("text", "") for e in rejected))

        # slash with no agent still dispatches fine (commands don't need the LLM)
        ok = controller.dispatch("/files")
        check("commands work without LLM", ok[0]["type"] == "table")

        # ── 9. skills via controller ───────────────────────────────────
        root = Path(tmp)
        skill_dir = root / ".rex" / "skills" / "greet"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Greet\nSapa pengguna dengan ramah.\n", encoding="utf-8")
        with patch("rex.skills.skills_dir", return_value=root / ".rex" / "skills"):
            events = controller.dispatch("/skill greet")
        check("/skill emits submit_prompt", any(e["type"] == "submit_prompt" and "Sapa pengguna" in e["text"] for e in events))
        with patch("rex.skills.skills_dir", return_value=root / ".rex" / "skills"):
            events = controller.dispatch("/skills")
        check("/skills lists", any(e["type"] == "table" and "greet" in e["text"] for e in events))

        # ── 10. auto-resume on first construction ──────────────────────
        store2 = SessionStore(Path(tmp) / "s2")
        sid = store2.create("gemini", "m1")["id"]
        store2.append(sid, {"role": "user", "content": "pekerjaan tertunda"})
        with patch("rex.app_controller.session_store", store2), \
             patch("rex.app_controller.RexAgent", FakeAgent), \
             patch("rex.app_controller.get_active_provider_info", return_value=("gemini", {}, "m1")):
            controller2 = ChatController()  # auto_resume=True default
        check("auto-resume picks newest open session", controller2.session_id == sid)
        check("resumed note queued", any("pekerjaan" in e["text"] or "dilanjutkan" in e["text"] for e in controller2.initial_events()))

    print("\nAll app_controller checks PASS")


if __name__ == "__main__":
    main()
