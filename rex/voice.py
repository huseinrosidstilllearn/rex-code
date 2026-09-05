"""
rex.voice
Voice input (Whisper) transcription service for Rex Code.

Three engines, zero required new dependencies:
  - "gemini"  -> google-genai (already installed), uses GEMINI_API_KEY
  - "openai"  -> openai SDK (already installed), uses /audio/transcriptions
  - "local"   -> optional faster-whisper (pip install faster-whisper), runs offline

Set `voice.engine` in config.json to "auto" (default), "gemini", "openai", or "local".
With "auto", engines are tried in order and each is skipped silently when its
API key or package is missing.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional

from rex.config import load_config, normalize_config

DEFAULT_VOICE_CONFIG = {
    "engine": "auto",            # "auto" | "gemini" | "openai" | "local"
    "model": "gemini-2.5-flash", # Gemini model that accepts audio input
    "api_key_env": "OPENAI_API_KEY",
    "api_model": "whisper-1",    # OpenAI-compatible transcription model
    "base_url": None,            # Optional OpenAI-compatible base URL for audio
    "local_model": "base",       # faster-whisper model size
}

VALID_VOICE_ENGINES = ("auto", "gemini", "openai", "local")


class VoiceTranscriptionError(Exception):
    """Raised when no engine could transcribe the audio."""


class _EngineUnavailable(Exception):
    """Raised internally when an engine lacks its key/package (skip, no retry)."""


def get_voice_config() -> dict:
    """Return the normalized voice section of config.json."""
    cfg = normalize_config(load_config())
    return cfg.get("voice", DEFAULT_VOICE_CONFIG)


class _GeminiTranscriber:
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def transcribe(self, data: bytes, mime_type: str) -> str:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)
        response = client.models.generate_content(
            model=self.model,
            contents=types.Part.from_bytes(data=data, mime_type=mime_type),
        )
        text = (response.text or "").strip()
        if not text:
            raise VoiceTranscriptionError(
                "Gemini tidak mengembalikan transkripsi. Coba audio yang lebih jelas."
            )
        return text


class _OpenAITranscriber:
    def __init__(self, api_key: str, model: str, base_url: Optional[str]):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

    def transcribe(self, data: bytes, mime_type: str) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key, base_url=self.base_url or None)
        response = client.audio.transcriptions.create(
            model=self.model,
            file=("voice.webm", data, mime_type),
        )
        text = (response.text or "").strip()
        if not text:
            raise VoiceTranscriptionError(
                "Engine OpenAI tidak mengembalikan transkripsi."
            )
        return text


class _LocalTranscriber:
    def __init__(self, model: str):
        self.model = model

    def transcribe(self, data: bytes, mime_type: str) -> str:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise _EngineUnavailable(
                "faster-whisper belum terinstall. Jalankan: pip install faster-whisper"
            )
        model = WhisperModel(self.model)
        segments, _info = model.transcribe(data, vad_filter=True)
        return "".join(segment.text for segment in segments).strip()


def _faster_whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _transcribe_with(engine: str, data: bytes, mime_type: str, cfg: dict) -> str:
    if engine == "gemini":
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            raise _EngineUnavailable("GEMINI_API_KEY belum diisi di .env")
        return _GeminiTranscriber(api_key, cfg.get("model") or "gemini-2.5-flash").transcribe(data, mime_type)
    if engine == "openai":
        api_key = os.getenv(cfg.get("api_key_env") or "OPENAI_API_KEY", "")
        if not api_key:
            raise _EngineUnavailable(
                f"{cfg.get('api_key_env') or 'OPENAI_API_KEY'} belum diisi di .env"
            )
        return _OpenAITranscriber(
            api_key,
            cfg.get("api_model") or "whisper-1",
            cfg.get("base_url"),
        ).transcribe(data, mime_type)
    if engine == "local":
        if not _faster_whisper_available():
            raise _EngineUnavailable("faster-whisper belum terinstall")
        return _LocalTranscriber(cfg.get("local_model") or "base").transcribe(data, mime_type)
    raise _EngineUnavailable(f"Engine transkripsi '{engine}' tidak dikenal")


def transcribe_audio(data: bytes, mime_type: str = "audio/webm") -> str:
    """
    Transcribe raw audio bytes with the configured engine.
    With engine "auto", each engine is tried in order and skipped when its
    API key or package is missing; real API errors propagate.
    """
    cfg = get_voice_config()
    engines: List[str] = (
        ["gemini", "openai", "local"] if cfg["engine"] == "auto" else [cfg["engine"]]
    )
    skipped: List[str] = []
    for engine in engines:
        try:
            return _transcribe_with(engine, data, mime_type, cfg)
        except _EngineUnavailable as exc:
            skipped.append(f"{engine}: {exc}")
            continue
    details = "; ".join(skipped) if skipped else "Tidak ada engine transkripsi tersedia"
    raise VoiceTranscriptionError(
        "Voice input tidak dapat memproses audio. " + details
    )


def transcribe_file(path: str) -> str:
    """Transcribe an audio file on disk (used by CLI)."""
    audio_path = Path(path)
    mime_type = _mime_for_suffix(audio_path.suffix)
    data = audio_path.read_bytes()
    return transcribe_audio(data, mime_type)


def _mime_for_suffix(suffix: str) -> str:
    return {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
        ".m4a": "audio/mp4",
        ".webm": "audio/webm",
    }.get(suffix.lower(), "audio/webm")


def engine_status() -> Dict[str, bool]:
    """Report which engines are ready (key present / package installed). No network calls."""
    cfg = get_voice_config()
    return {
        "gemini": bool(os.getenv("GEMINI_API_KEY", "")),
        "openai": bool(os.getenv(cfg.get("api_key_env") or "OPENAI_API_KEY", "")),
        "local": _faster_whisper_available(),
    }