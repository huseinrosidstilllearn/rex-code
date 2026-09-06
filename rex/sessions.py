"""Local JSON conversation persistence."""

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from rex.config import SESSIONS_DIR


SESSION_ID_RE = re.compile(r"^[0-9a-f]{32}$")
SECRET_KEYS = ("api_key", "apikey", "authorization", "password", "secret", "token")


class SessionStore:
    def __init__(self, directory: Path = SESSIONS_DIR, max_content_chars: int = 8000):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.max_content_chars = max(100, int(max_content_chars))
        self._lock = threading.RLock()

    def _path(self, session_id: str) -> Path:
        if not SESSION_ID_RE.fullmatch(str(session_id)):
            raise ValueError("Session ID tidak valid")
        return self.directory / f"{session_id}.json"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _safe(self, value: Any, key: str = "") -> Any:
        if any(secret in key.lower() for secret in SECRET_KEYS):
            return "[REDACTED]"
        if isinstance(value, dict):
            return {str(k): self._safe(v, str(k)) for k, v in value.items()}
        if isinstance(value, list):
            return [self._safe(item) for item in value]
        if isinstance(value, str):
            for env_key, secret in os.environ.items():
                if any(word in env_key.lower() for word in SECRET_KEYS) and len(secret) >= 8:
                    value = value.replace(secret, "[REDACTED]")
            if len(value) > self.max_content_chars:
                return value[: self.max_content_chars - 14] + "\n...[dipotong]"
        return value

    def _write(self, data: Dict[str, Any]) -> None:
        path = self._path(data["id"])
        temp = path.with_suffix(".tmp")
        with open(temp, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, path)

    def create(self, provider: str, model: str) -> Dict[str, Any]:
        now = self._now()
        data = {
            "id": uuid.uuid4().hex,
            "title": "Percakapan baru",
            "created_at": now,
            "updated_at": now,
            "provider": str(provider),
            "model": str(model),
            "status": "open",
            "messages": [],
        }
        with self._lock:
            self._write(data)
        return data

    def load(self, session_id: str) -> Dict[str, Any]:
        path = self._path(session_id)
        with self._lock:
            if not path.exists():
                raise FileNotFoundError(session_id)
            with open(path, "r", encoding="utf-8") as file:
                return json.load(file)

    def list(self) -> List[Dict[str, Any]]:
        sessions = []
        with self._lock:
            for path in self.directory.glob("*.json"):
                try:
                    with open(path, "r", encoding="utf-8") as file:
                        data = json.load(file)
                    sessions.append({key: data.get(key) for key in (
                        "id", "title", "created_at", "updated_at", "provider", "model", "usage", "status"
                    )})
                except (OSError, json.JSONDecodeError):
                    continue
        return sorted(sessions, key=lambda item: item.get("updated_at") or "", reverse=True)

    def append(self, session_id: str, message: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            data = self.load(session_id)
            safe_message = self._safe(message)
            data["messages"].append(safe_message)
            if data["title"] == "Percakapan baru" and safe_message.get("role") == "user":
                title = str(safe_message.get("content", "")).strip().replace("\n", " ")
                data["title"] = title[:60] or data["title"]
            data["updated_at"] = self._now()
            self._write(data)
            return safe_message

    def model_messages(self, session_id: str, limit: int = 40) -> List[Dict[str, Any]]:
        messages = self.load(session_id).get("messages", [])
        return messages[-max(1, int(limit)):]

    def add_usage(self, session_id: str, usage: Any) -> Optional[Dict[str, int]]:
        """Accumulate one response's token usage into the session record.
        Returns the stored totals, or None on any failure. Never raises."""
        try:
            prompt = int(getattr(usage, "prompt_tokens", None) or 0)
            completion = int(getattr(usage, "completion_tokens", None) or 0)
            total = int(getattr(usage, "total_tokens", None) or (prompt + completion))
            with self._lock:
                data = self.load(session_id)
                stored = data.get("usage")
                if not isinstance(stored, dict):
                    stored = {}
                stored["prompt_tokens"] = int(stored.get("prompt_tokens", 0) or 0) + prompt
                stored["completion_tokens"] = int(stored.get("completion_tokens", 0) or 0) + completion
                stored["total_tokens"] = int(stored.get("total_tokens", 0) or 0) + total
                data["usage"] = stored
                data["updated_at"] = self._now()
                self._write(data)
                return dict(stored)
        except Exception:
            return None

    def delete(self, session_id: str) -> None:
        path = self._path(session_id)
        with self._lock:
            if not path.exists():
                raise FileNotFoundError(session_id)
            path.unlink()

    def close(self, session_id: str) -> None:
        """Mark a session cleanly ended. Crash recovery only offers sessions
        that are still ``"open"`` — a clean exit must land here."""
        with self._lock:
            data = self.load(session_id)
            if data.get("status") != "closed":
                data["status"] = "closed"
                data["updated_at"] = self._now()
                self._write(data)

    def last_open_session(self) -> Optional[Dict[str, Any]]:
        """
        Newest session still marked ``"open"`` with at least one message —
        the auto-resume candidate after a crash. Sessions written before
        this field existed never qualify. Returns None when there is none.
        """
        with self._lock:
            for meta in self.list():
                try:
                    data = self.load(meta["id"])
                except Exception:
                    continue
                if data.get("status") == "open" and data.get("messages"):
                    return {
                        "id": data["id"],
                        "title": data.get("title"),
                        "provider": data.get("provider"),
                        "model": data.get("model"),
                        "updated_at": data.get("updated_at"),
                        "message_count": len(data["messages"]),
                    }
        return None


session_store = SessionStore()