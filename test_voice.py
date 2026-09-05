"""Self-check voice input (Whisper) service. Run: python test_voice.py"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rex.voice as voice
from rex.config import DEFAULT_CONFIG, normalize_config


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        sys.exit(1)


def main():
    # 1. Voice defaults merged + invalid engine repaired
    cfg = normalize_config({"active_provider": "gemini"})
    check("voice defaults present", cfg.get("voice", {}).get("engine") == "auto")
    check(
        "voice model defaulted",
        cfg["voice"]["model"] == DEFAULT_CONFIG["voice"]["model"],
    )
    bad = normalize_config({"voice": {"engine": "telepati"}})
    check("invalid voice engine repaired", bad["voice"]["engine"] == "auto")
    custom = normalize_config({"voice": {"engine": "openai", "api_model": "whisper-large-v3"}})
    check("custom voice values kept", custom["voice"]["engine"] == "openai"
          and custom["voice"]["api_model"] == "whisper-large-v3")

    # 2. Auto engine with no keys skips and reports clearly
    cfg = {"engine": "auto", "model": "gemini-2.5-flash", "api_key_env": "OPENAI_API_KEY",
           "api_model": "whisper-1", "base_url": None, "local_model": "base"}
    with patch.dict(os.environ, {}, clear=True), \
         patch("rex.voice.get_voice_config", return_value=cfg), \
         patch("rex.voice._faster_whisper_available", return_value=False):
        try:
            voice.transcribe_audio(b"\x00audio", "audio/wav")
            check("no-engine raises helpful error", False)
        except voice.VoiceTranscriptionError as exc:
            check("no-engine raises helpful error", "GEMINI_API_KEY" in str(exc))

    # 3. Gemini engine transcribes (mocked client)
    class FakeGemini:
        def __init__(self, api_key, model):
            self.api_key = api_key
            self.model = model

        def transcribe(self, data, mime_type):
            assert mime_type == "audio/wav"
            return "Halo Rex, buatkan landing page"

    with patch.dict(os.environ, {"GEMINI_API_KEY": "AIza-test"}, clear=True), \
         patch("rex.voice.get_voice_config", return_value=cfg), \
         patch("rex.voice._GeminiTranscriber", FakeGemini):
        text = voice.transcribe_audio(b"audio", "audio/wav")
    check("gemini engine transcribes", text == "Halo Rex, buatkan landing page")

    # 4. OpenAI engine transcribes (mocked client)
    class FakeOpenAI:
        def __init__(self, api_key, model, base_url):
            self.api_key = api_key
            self.model = model
            self.base_url = base_url

        def transcribe(self, data, mime_type):
            assert self.model == "whisper-1"
            return "Buatkan workflow n8n"

    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True), \
         patch("rex.voice.get_voice_config", return_value={**cfg, "engine": "openai"}), \
         patch("rex.voice._OpenAITranscriber", FakeOpenAI):
        text = voice.transcribe_audio(b"audio", "audio/webm")
    check("openai engine transcribes", text == "Buatkan workflow n8n")

    # 5. Auto falls back from unavailable gemini to working openai
    class FakeOpenAI2:
        def __init__(self, api_key, model, base_url):
            pass

        def transcribe(self, data, mime_type):
            return "dari fallback"

    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True), \
         patch("rex.voice.get_voice_config", return_value=cfg), \
         patch("rex.voice._GeminiTranscriber") as fake_gemini, \
         patch("rex.voice._OpenAITranscriber", FakeOpenAI2):
        fake_gemini.side_effect = ImportError("google genai missing")
        text = voice.transcribe_audio(b"audio", "audio/wav")
    check("auto engine falls back", text == "dari fallback")

    # 6. Local engine missing package -> skipped with clear message
    with patch.dict(os.environ, {}, clear=True), \
         patch("rex.voice.get_voice_config", return_value={**cfg, "engine": "local"}), \
         patch("rex.voice._faster_whisper_available", return_value=False):
        try:
            voice.transcribe_audio(b"audio", "audio/wav")
            check("local missing package reported", False)
        except voice.VoiceTranscriptionError as exc:
            check("local missing package reported", "faster-whisper" in str(exc))

    # 7. Unknown engine
    with patch("rex.voice.get_voice_config", return_value={**cfg, "engine": "klingon"}):
        try:
            voice.transcribe_audio(b"audio", "audio/wav")
            check("unknown engine reported", False)
        except voice.VoiceTranscriptionError as exc:
            check("unknown engine reported", "klingon" in str(exc))

    # 8. transcribe_file maps suffix to mime and reads bytes
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        sample = Path(tmp) / "sampel.wav"
        sample.write_bytes(b"\x52\x49\x46\x46")
        with patch("rex.voice.transcribe_audio", return_value="dari file") as mocked:
            text = voice.transcribe_file(str(sample))
            mocked.assert_called_once()
            args = mocked.call_args[0]
            check("transcribe_file passes wav mime", text == "dari file" and args[1] == "audio/wav")

    # 9. engine_status reflects available keys
    with patch.dict(os.environ, {"GEMINI_API_KEY": "AIza-x"}, clear=True), \
         patch("rex.voice._faster_whisper_available", return_value=True), \
         patch("rex.voice.get_voice_config", return_value=cfg):
        status = voice.engine_status()
    check("engine_status detects gemini", status["gemini"] is True)
    check("engine_status detects local", status["local"] is True)
    check("engine_status detects missing openai", status["openai"] is False)

    print("\nVoice checks 14/14 PASS")


if __name__ == "__main__":
    main()