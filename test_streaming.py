"""Self-check provider and agent streaming. Run: python test_streaming.py"""

import tempfile
from pathlib import Path
from unittest.mock import patch

from rex.providers.base import LLMResponse, StreamEvent
from rex.providers.gemini import GeminiProvider
from rex.sessions import SessionStore


class Chunk:
    def __init__(self, text):
        self.text = text


class FakeChat:
    def send_message_stream(self, message):
        assert message == "uji"
        return iter([Chunk("Halo "), Chunk("Gemini")])


class FakeRouter:
    def chat_stream(self, messages, system_prompt, tools=None):
        yield StreamEvent("text", "Halo ")
        yield StreamEvent("text", "Router")
        yield StreamEvent("final", LLMResponse("Halo Router"))

    def chat(self, messages, system_prompt, tools=None):
        raise AssertionError("Non-stream path dipakai")


def main():
    gemini = GeminiProvider.__new__(GeminiProvider)
    gemini.chat_session = FakeChat()
    events = list(gemini.chat_simple_stream("uji", "sistem"))
    assert [event.data for event in events if event.kind == "text"] == ["Halo ", "Gemini"]
    assert events[-1].data.content == "Halo Gemini"

    with tempfile.TemporaryDirectory() as temp_dir:
        store = SessionStore(Path(temp_dir))
        session_id = store.create("custom", "mock")["id"]
        emitted = []
        with patch("rex.core.session_store", store), \
             patch("rex.core.get_llm_provider", return_value=FakeRouter()), \
             patch("rex.core.load_config", return_value={"stream_enabled": True, "anti_slop_enabled": False, "max_steps": 2}):
            from rex.core import RexAgent
            result = RexAgent(session_id).run("Mulai", on_step=lambda event: emitted.append(event))
        assert result == "Halo Router"
        assert [event.data for event in emitted if event.event_type == "stream_delta"] == ["Halo ", "Router"]
        saved = store.load(session_id)["messages"]
        assert saved == [{"role": "user", "content": "Mulai"}, {"role": "assistant", "content": "Halo Router"}]

    print("Streaming checks 6/6 PASS")


if __name__ == "__main__":
    main()