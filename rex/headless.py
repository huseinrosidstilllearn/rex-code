"""
rex.headless
============
Non-interactive one-shot runs: ``python cli.py -p "prompt" [--json]``.

Safety posture: destructive BUILD actions are DENIED by default. Scripts
and CI must pass ``--yolo`` explicitly to allow them. Output is plain text
by default or a machine-readable JSON object with ``--json``.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

from rex.approval import set_override_settings, set_provider, reset_session_allows
from rex.core import RexAgent
from rex.config import get_active_mode, set_active_mode, normalize_config, load_config


def _deny_all_provider(action: str, summary: str) -> bool:
    """Headless without --yolo: refuse every action that wants approval."""
    return False


def run_headless(
    prompt: str,
    session_id: Optional[str] = None,
    mode: Optional[str] = None,
    yolo: bool = False,
) -> Dict[str, Any]:
    """
    Run one prompt through the agent and return a structured result dict.
    Keys: response, mode, provider, model, session, usage, elapsed_ms,
    and on failure: ok=False, error.
    """
    started = time.monotonic()
    cfg = normalize_config(load_config())
    provider_id = cfg.get("active_provider", "?")
    model = cfg.get("active_model", "?")

    if mode:
        set_active_mode(mode)

    # Safety posture for unattended runs.
    if yolo:
        set_override_settings(None)  # follow config.json as-is
    else:
        set_override_settings({"enabled": True, "actions": [], "allow": {}})
        set_provider(_deny_all_provider)

    result: Dict[str, Any] = {
        "ok": True,
        "response": "",
        "mode": get_active_mode(),
        "provider": provider_id,
        "model": model,
        "session": session_id or "",
        "usage": None,
        "elapsed_ms": 0,
    }

    try:
        agent = RexAgent(session_id)
        result["session"] = agent.session_id or session_id or ""
        answer = agent.run(prompt)
        result["response"] = answer
        result["usage"] = dict(agent.total_usage)
        result["provider_failed"] = "Provider gagal memproses permintaan" in answer
    except Exception as exc:  # unattended: never crash without a message
        result["ok"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        set_override_settings(None)
        set_provider(None)
        reset_session_allows()

    result["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    return result


def format_result_text(result: Dict[str, Any]) -> str:
    """Human-readable single-shot output."""
    if not result.get("ok"):
        return f"[ERROR] {result.get('error', 'unknown failure')}"
    return result.get("response", "")


def format_result_json(result: Dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2)
