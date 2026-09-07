"""Settings Center API — providers CRUD, general settings, .env key vault.

Contract rules (Sprint v0.3.1 Fase C):
- API keys are written ONLY to the .env vault (ENV_FILE), never to config.json.
- config.json keeps provider metadata (name, base_url, api_key_env, model).
- provider_test() performs a real round-trip before a key is trusted.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

from rex.config import (
    DEFAULT_CONFIG,
    ENV_FILE,
    load_config,
    save_config,
    normalize_config,
)

# General settings fields exposed in the Settings Center, mapped to
# config.json keys. (ui_key, config_key, choices)
_SETTINGS_KEYS = [
    ("default_mode", "active_mode", ("plan", "build")),
    ("streaming", "stream_enabled", ("on", "off")),
    ("anti_slop", "anti_slop_enabled", ("on", "off")),
    ("language", "language", None),
    ("update_channel", "update_channel", ("stable", "beta")),
    ("token_budget", "token_budget", None),
    ("max_steps", "max_steps", None),
    ("terminal_timeout", "terminal_timeout_sec", None),
    ("max_history", "max_history_messages", None),
    ("approval", "approval_mode", ("on", "off")),
]


def settings_get() -> Dict[str, object]:
    cfg = load_config()
    return {
        "ok": True,
        "settings": {
            "default_mode": cfg.get("active_mode", "plan"),
            "token_budget": cfg.get("token_budget", 0),
            "max_steps": cfg.get("max_steps", 25),
            "streaming": "on" if cfg.get("stream_enabled", True) else "off",
            "anti_slop": "on" if cfg.get("anti_slop_enabled", True) else "off",
            "terminal_timeout": cfg.get("terminal_timeout_sec", 45),
            "max_history": cfg.get("max_history_messages", 40),
        },
    }


def settings_update(body: dict) -> Dict[str, object]:
    cfg = load_config()
    _INT_KEYS = ("token_budget", "max_steps", "terminal_timeout", "max_history")
    _BOOL_KEYS = ("streaming", "anti_slop")
    for ui_key, cfg_key, choices in _SETTINGS_KEYS:
        if ui_key not in body:
            continue
        value = body[ui_key]
        if choices is not None and str(value) not in choices:
            return {"ok": False, "error": "invalid value for " + ui_key}
        if ui_key in _INT_KEYS:
            try:
                value = int(value)
            except (TypeError, ValueError):
                return {"ok": False, "error": ui_key + " must be a number"}
            if value < 0:
                return {"ok": False, "error": ui_key + " must be >= 0"}
        if ui_key in _BOOL_KEYS:
            value = str(value) == "on"
        cfg[cfg_key] = value
    save_config(cfg)
    return {"ok": True, "settings": settings_get()["settings"]}


# ── providers ───────────────────────────────────────────────
def providers_list() -> Dict[str, object]:
    cfg = load_config()
    providers = cfg.get("providers") or {}
    items = []
    for pid, p in providers.items():
        key_env = str(p.get("api_key_env") or "")
        items.append({
            "id": pid,
            "name": p.get("name") or pid,
            "base_url": p.get("base_url") or "",
            "model": p.get("model") or "",
            "api_key_env": key_env,
            "has_key": bool(key_env and os.getenv(key_env)),
            "available_models": p.get("available_models") or [],
        })
    items.sort(key=lambda x: (x["id"] != cfg.get("active_provider"), x["name"]))
    return {"ok": True, "providers": items, "active": cfg.get("active_provider")}


def _provider(cfg: dict, pid: str) -> Optional[dict]:
    p = (cfg.get("providers") or {}).get(pid)
    return p if p else None


def provider_mutate(body: dict) -> Dict[str, object]:
    action = str(body.get("action") or "")
    pid = str(body.get("id") or "")
    cfg = load_config()
    providers = cfg.setdefault("providers", {})

    if action == "activate":
        p = _provider(cfg, pid)
        if not p:
            return {"ok": False, "error": "unknown provider"}
        cfg["active_provider"] = pid
        if p.get("model"):
            cfg["active_model"] = p["model"]
        save_config(cfg)
        return {"ok": True, "active": pid}

    if action == "update":
        p = _provider(cfg, pid)
        if not p:
            return {"ok": False, "error": "unknown provider"}
        data = body.get("data") or {}
        if "name" in data and str(data.get("name") or "").strip():
            p["name"] = str(data["name"]).strip()
        if "base_url" in data:
            p["base_url"] = str(data["base_url"] or "").strip()
        if "model" in data and str(data.get("model") or "").strip():
            p["model"] = str(data["model"]).strip()
            if cfg.get("active_provider") == pid:
                cfg["active_model"] = p["model"]
        if "available_models" in data and isinstance(data["available_models"], list):
            p["available_models"] = [str(m) for m in data["available_models"]]
        save_config(cfg)
        if data.get("api_key"):
            return key_write({
                "id": pid,
                "api_key_env": p.get("api_key_env") or "",
                "api_key": str(data["api_key"]),
            })
        return {"ok": True}

    if action == "add":
        new_id = str(body.get("id") or "").strip()
        if not new_id or not new_id.replace("_", "").isalnum():
            return {"ok": False, "error": "id must be alnum/underscore"}
        if new_id in providers:
            return {"ok": False, "error": "provider id exists"}
        data = body.get("data") or {}
        providers[new_id] = {
            "name": str(data.get("name") or new_id),
            "base_url": str(data.get("base_url") or ""),
            "api_key_env": str(data.get("api_key_env") or (new_id.upper() + "_API_KEY")),
            "model": str(data.get("model") or ""),
            "available_models": [str(m) for m in (data.get("available_models") or [])],
        }
        save_config(cfg)
        return {"ok": True, "id": new_id}

    if action == "delete":
        if pid not in providers:
            return {"ok": False, "error": "unknown provider"}
        if pid == cfg.get("active_provider"):
            return {"ok": False, "error": "cannot delete the active provider"}
        del providers[pid]
        save_config(cfg)
        return {"ok": True}

    return {"ok": False, "error": "action?"}


def key_write(body: dict) -> Dict[str, object]:
    """Persist an API key to the .env vault. Never touches config.json."""
    key_env = str(body.get("api_key_env") or "").strip()
    api_key = str(body.get("api_key") or "").strip()
    pid = str(body.get("id") or "").strip()
    if not key_env or not api_key:
        return {"ok": False, "error": "api_key_env and api_key required"}
    if not key_env.replace("_", "").isupper() or not key_env.replace("_", "").isalpha():
        return {"ok": False, "error": "api_key_env must be UPPER_SNAKE"}
    try:
        ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
        lines: List[str] = []
        if ENV_FILE.exists():
            lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
        replaced = False
        for i, line in enumerate(lines):
            if line.strip().startswith("#") or "=" not in line:
                continue
            if line.split("=", 1)[0].strip() == key_env:
                lines[i] = key_env + "=" + api_key
                replaced = True
                break
        if not replaced:
            lines.append(key_env + "=" + api_key)
        ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.environ[key_env] = api_key  # live without restart
        try:
            ENV_FILE.chmod(0o600)
        except (OSError, NotImplementedError):
            pass  # Windows ACLs govern here
        return {"ok": True, "id": pid, "api_key_env": key_env}
    except OSError as exc:
        return {"ok": False, "error": "write failed: " + str(exc)}


def provider_test(pid: str, model: Optional[str] = None) -> Dict[str, object]:
    """One real round-trip through the provider's chat endpoint."""
    cfg = load_config()
    p = _provider(cfg, pid)
    if not p:
        return {"ok": False, "error": "unknown provider"}
    key_env = str(p.get("api_key_env") or "")
    api_key = os.getenv(key_env, "")
    if not api_key:
        return {"ok": False, "error": "API key kosong — set " + key_env + " dulu"}
    base_url = (p.get("base_url") or "").rstrip("/")
    if not base_url:
        return {"ok": False, "error": "base_url kosong"}
    target_model = str(model or p.get("model") or "")
    if not target_model:
        return {"ok": False, "error": "model kosong"}
    try:
        import json as _json
        import urllib.request
        payload = _json.dumps({
            "model": target_model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 8,
        }).encode("utf-8")
        req = urllib.request.Request(
            base_url + "/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = _json.loads(resp.read().decode("utf-8"))
        n = len(body.get("choices") or [])
        return {"ok": True, "detail": target_model + " menjawab (" + str(n) + " pilihan)"}
    except Exception as exc:  # noqa: BLE001 — surface any transport error to UI
        return {"ok": False, "error": str(exc)}


def onboarding_status() -> Dict[str, object]:
    cfg = load_config()
    active = str(cfg.get("active_provider") or "")
    p = (cfg.get("providers") or {}).get(active) or {}
    key_env = str(p.get("api_key_env") or "")
    has_key = bool(key_env and os.getenv(key_env))
    return {
        "ok": True,
        "needed": not has_key,
        "provider": active,
        "api_key_env": key_env,
        "model": p.get("model") or cfg.get("active_model") or "",
    }


def onboarding_complete(body: dict) -> Dict[str, object]:
    """Wizard step: (optionally switch provider) + save key + verify."""
    pid = str(body.get("provider") or "")
    api_key = str(body.get("api_key") or "").strip()
    model = str(body.get("model") or "").strip()
    cfg = load_config()
    if pid:
        p = _provider(cfg, pid)
        if not p:
            return {"ok": False, "error": "unknown provider"}
        cfg["active_provider"] = pid
        if model:
            p["model"] = model
            cfg["active_model"] = model
        elif p.get("model"):
            cfg["active_model"] = p["model"]
        save_config(cfg)
        if api_key:
            key_write({"id": pid, "api_key_env": p.get("api_key_env") or "", "api_key": api_key})
    if api_key:
        result = provider_test(pid or str(cfg.get("active_provider") or ""))
        if not result.get("ok"):
            return result
    return {"ok": True}
