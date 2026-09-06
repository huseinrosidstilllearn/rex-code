"""
rex.approval
============
Per-action approval for BUILD mode.

Every destructive BUILD tool (write_file, edit_file, delete_file, run_command,
git_publish) consults :func:`request_approval` right before it acts. The UI
(CLI or TUI) registers a *provider* — a callable that asks the human and
returns True/False. When no provider is registered (tests, scripts, headless
runs) the gate fails open so existing behavior is unchanged.

Config (config.json -> "approval"):

    "approval": {
        "enabled": false,          # master switch (default: off = old behavior)
        "actions": [],             # empty = all destructive actions; or e.g.
                                   # ["run_command", "git_publish"]
        "allow": {                 # session-level allow patterns, see below
        }
    }

Session-level allowlist: while a session runs, the user may answer
"always" to a prompt; that stores an entry like ``run_command:pip install*``
(glob, case-insensitive) in :data:`_session_allows` so identical future
actions do not re-prompt. Entries live in memory only — every new session
asks again.
"""

from __future__ import annotations

import fnmatch
import threading
from typing import Callable, Dict, Optional

from rex.logging_setup import log

# Provider hook: set by the active UI (CLI console or TUI modal).
# Signature: provider(action: str, summary: str) -> bool
_provider: Optional[Callable[[str, str], bool]] = None
_provider_lock = threading.Lock()

# Process-wide settings override (headless mode, tests). When set, takes
# precedence over config.json so entry points can enforce a safety posture
# without touching the user's on-disk configuration.
_override_settings: Optional[dict] = None

# session-level "always allow" patterns: {"action": ["glob", ...]}
_session_allows: Dict[str, list] = {}
_allows_lock = threading.Lock()

DESTRUCTIVE_ACTIONS = (
    "write_file", "edit_file", "delete_file", "run_command", "git_publish",
    "mcp_tool", "plugin_tool",  # external code: gated like built-in destructive tools
)

# Key-name markers used to redact secrets from summaries, logs, and output.
SECRET_MARKERS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "PRIVATE_KEY", "CREDENTIAL")


def set_provider(provider: Optional[Callable[[str, str], bool]]) -> None:
    """Register the UI confirmation hook (or None to disable prompting)."""
    global _provider
    with _provider_lock:
        _provider = provider


def reset_session_allows() -> None:
    """Clear session-level 'always allow' entries (new session / tests)."""
    with _allows_lock:
        _session_allows.clear()


def set_override_settings(settings: Optional[dict]) -> None:
    """Force approval settings for this process (None = read config.json)."""
    global _override_settings
    _override_settings = settings


def _get_settings(cfg: Optional[dict] = None) -> dict:
    if _override_settings is not None:
        return _override_settings
    if cfg is None:
        from rex.config import load_config, normalize_config
        cfg = normalize_config(load_config())
    settings = cfg.get("approval", {})
    return settings if isinstance(settings, dict) else {}


def _matches_allow(action: str, summary: str, allow_map: dict) -> bool:
    patterns = allow_map.get(action) or []
    lowered = summary.lower()
    return any(
        isinstance(p, str) and fnmatch.fnmatch(lowered, p.lower())
        for p in patterns
    )


def request_approval(action: str, summary: str, cfg: Optional[dict] = None) -> bool:
    """
    Return True when the action may proceed.

    Fail-open rules (no provider / disabled / action not gated / pattern
    already allowed) keep this a pure additive gate: nothing changes for
    users who do not opt in.
    """
    try:
        settings = _get_settings(cfg)
        if not settings.get("enabled", False):
            return True
        gated = settings.get("actions") or list(DESTRUCTIVE_ACTIONS)
        if action not in gated:
            return True
        if _matches_allow(action, summary, settings.get("allow") or {}):
            return True
        with _allows_lock:
            if _matches_allow(action, summary, _session_allows):
                return True

        with _provider_lock:
            provider = _provider
        if provider is None:
            # No UI attached (tests, scripts): fail open, log for traceability.
            log.debug(f"approval: no provider registered, auto-approving {action}")
            return True

        decision = provider(action, summary)
        if isinstance(decision, tuple) and len(decision) == 2:
            decision, remember = decision
            pattern: Optional[str] = None
            if isinstance(remember, str) and remember.strip():
                # Provider supplied a glob pattern to remember, e.g. "git *"
                pattern = remember.strip().lower()
            elif remember:
                # Truthy non-string (e.g. True) -> remember this exact action
                pattern = summary.lower()
            if pattern:
                with _allows_lock:
                    _session_allows.setdefault(action, []).append(pattern)
        return bool(decision)
    except Exception as exc:  # approval must never break the tool layer
        log.debug(f"approval error ({action}): {exc} — failing open")
        return True


def summarize_action(action: str, args: dict) -> str:
    """Human-readable one-liner of what the tool is about to do."""
    args = args or {}
    if action == "write_file":
        return f"tulis file {args.get('path', '?')}"
    if action == "edit_file":
        return f"edit file {args.get('path', '?')}"
    if action == "delete_file":
        return f"hapus file {args.get('path', '?')}"
    if action == "run_command":
        command = " ".join(str(args.get("command", "")).split())
        return f"jalankan perintah: {command[:120]}"
    if action == "git_publish":
        return f"commit & push: {str(args.get('message', ''))[:80]}"
    if action == "mcp_tool":
        return (f"eksekusi tool MCP '{args.get('tool', '?')}' (server: {args.get('server', '?')}): "
                f"{str(args.get('args', ''))[:120]}")
    if action == "plugin_tool":
        return f"eksekusi tool plugin '{args.get('tool', '?')}': {str(args.get('args', ''))[:120]}"
    return f"{action} {args}"
