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
        with patch("rex.core.session_store", store), patch("rex.core.get_llm_provider", return_value=provider):
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

    print("Session checks 10/10 PASS")


if __name__ == "__main__":
    main()