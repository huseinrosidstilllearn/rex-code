"""Self-check for persistent conversation behavior. Run: python test_sessions.py"""

import tempfile
from pathlib import Path
from unittest.mock import patch

from rex.sessions import SessionStore
from rex.providers.base import LLMResponse


class FakeProvider:
    def __init__(self):
        self.received = []

    def chat(self, messages, system_prompt, tools=None):
        self.received = messages.copy()
        return LLMResponse(content="Konteks diterima")


def main():
    with tempfile.TemporaryDirectory() as temp_dir:
        store = SessionStore(Path(temp_dir), max_content_chars=500)
        session = store.create("custom", "test-model")
        session_id = session["id"]

        store.append(session_id, {"role": "user", "content": "Bangun API tugas"})
        store.append(session_id, {
            "role": "tool",
            "name": "run_command",
            "content": "x" * 900,
            "args": {"api_key": "rahasia", "command": "echo aman"},
        })
        store.append(session_id, {"role": "assistant", "content": "API selesai"})

        loaded = store.load(session_id)
        assert loaded["title"] == "Bangun API tugas"
        assert loaded["messages"][1]["args"]["api_key"] == "[REDACTED]"
        assert len(loaded["messages"][1]["content"]) <= 500
        assert store.model_messages(session_id, limit=2) == loaded["messages"][-2:]
        assert store.list()[0]["id"] == session_id

        provider = FakeProvider()
        with patch("rex.core.session_store", store), patch("rex.core.get_llm_provider_with_fallback", return_value=(provider, [None])):
            from rex.core import RexAgent
            agent = RexAgent(session_id=session_id)
            agent.run("Lanjutkan")
        assert provider.received[0]["content"] == "Bangun API tugas"
        assert provider.received[-1]["content"] == "Lanjutkan"

        store.delete(session_id)
        assert store.list() == []
        try:
            store.load("../config")
            raise AssertionError("Traversal session ID diterima")
        except (FileNotFoundError, ValueError):
            pass

    # ── Session resume + crash recovery ───────────────────────────────
    with tempfile.TemporaryDirectory() as temp_dir:
        store = SessionStore(Path(temp_dir))

        # Fresh session is born open
        s1 = store.create("gemini", "m1")
        assert s1["status"] == "open"
        assert store.last_open_session() is None  # no messages yet -> not a candidate

        store.append(s1["id"], {"role": "user", "content": "pekerjaan pertama"})
        assert store.last_open_session()["id"] == s1["id"]

        # A cleanly closed session is never a resume candidate
        store.close(s1["id"])
        assert store.load(s1["id"])["status"] == "closed"
        assert store.last_open_session() is None
        store.close(s1["id"])  # idempotent
        assert store.load(s1["id"])["status"] == "closed"

        # Newest open session wins; message_count reported
        s2 = store.create("gemini", "m2")
        s3 = store.create("gemini", "m3")
        store.append(s2["id"], {"role": "user", "content": "sesi dua"})
        store.append(s2["id"], {"role": "assistant", "content": "jawab dua"})
        store.append(s3["id"], {"role": "user", "content": "sesi tiga"})
        candidate = store.last_open_session()
        assert candidate["id"] == s3["id"], "newest open session must win"
        assert candidate["message_count"] == 1
        assert store.list()[0]["status"] == "open"

        # Missing status (old-format files) never qualifies
        import json
        path = store._path(s3["id"])
        data = json.loads(path.read_text(encoding="utf-8"))
        del data["status"]
        path.write_text(json.dumps(data), encoding="utf-8")
        assert store.last_open_session()["id"] == s2["id"]

        # Resume flow: a fresh agent pointed at the old session id reloads history
        provider = FakeProvider()
        with patch("rex.core.session_store", store), patch(
            "rex.core.get_llm_provider_with_fallback", return_value=(provider, [None])
        ):
            from rex.core import RexAgent
            agent = RexAgent(session_id=s2["id"])
            assert agent.messages[-1]["content"] == "jawab dua"
            agent.run("lanjut di sini")
        assert provider.received[0]["content"] == "sesi dua", "resumed context must reach the provider"
        assert provider.received[-1]["content"] == "lanjut di sini"

        try:
            store.close("tidak-ada")
            raise AssertionError("close pada id asing harus gagal")
        except (FileNotFoundError, ValueError):
            pass

    print("Session checks 24/24 PASS")


if __name__ == "__main__":
    main()