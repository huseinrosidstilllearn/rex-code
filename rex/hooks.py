"""
rex.hooks
=========
User-defined Pre/PostToolUse hooks from ``<workspace>/.rex/hooks.json``.

Schema::

    {
      "hooks": {
        "PreToolUse":  [{"matcher": "run_command|write_file", "command": "python guard.py", "timeout_sec": 10}],
        "PostToolUse": [{"matcher": "edit_file|apply_patch", "command": "black ."}]
      }
    }

Semantics (mirrors the Claude-Code convention, kept fail-open):

- Every hook receives one JSON payload on stdin —
  ``{"tool", "args"}`` before, ``{"tool", "args", "result"}`` after.
- ``PreToolUse``: exit code 2 DENIES the tool call (stdout becomes the
  reason shown to the model); exit 0 or any other code allows it.
  A crashing or timed-out hook never blocks — it is logged and skipped.
- ``PostToolUse``: exit 0 stdout (if any) is appended to the tool result
  as feedback; failures are logged and dropped.

Hooks run through the same sandbox as ``run_command``: workspace cwd,
secret-sanitized environment, hard timeout. A missing or malformed
hooks.json simply means "no hooks" — the feature is purely additive.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from rex.config import WORKSPACE_DIR, load_config
from rex.logging_setup import log
from rex.shell import build_command_argv
from rex.tools import _sanitized_environment

HOOKS_DIRNAME = ".rex"
HOOKS_FILENAME = "hooks.json"
MAX_HOOKS_PER_EVENT = 16
DEFAULT_TIMEOUT_SEC = 10
RESULT_PREVIEW_CHARS = 4000
DENY_EXIT_CODE = 2


def hooks_file(workspace: Optional[Path] = None) -> Path:
    """Path of the hooks config: ``<workspace>/.rex/hooks.json``."""
    root = Path(workspace) if workspace else WORKSPACE_DIR
    return root / HOOKS_DIRNAME / HOOKS_FILENAME


def _normalize_entries(raw: Any) -> List[dict]:
    """Keep only well-formed hook entries; clamp timeouts; cap the count."""
    if not isinstance(raw, list):
        return []
    entries: List[dict] = []
    for item in raw[:MAX_HOOKS_PER_EVENT]:
        if not isinstance(item, dict):
            continue
        command = item.get("command")
        if not isinstance(command, str) or not command.strip():
            continue
        matcher = item.get("matcher", ".*")
        if not isinstance(matcher, str) or not matcher.strip():
            matcher = ".*"
        try:
            timeout = int(item.get("timeout_sec", DEFAULT_TIMEOUT_SEC))
        except (TypeError, ValueError):
            timeout = DEFAULT_TIMEOUT_SEC
        entries.append({
            "matcher": matcher.strip(),
            "command": command.strip(),
            "timeout_sec": max(1, min(60, timeout)),
        })
    return entries


def load_hooks(workspace: Optional[Path] = None) -> Dict[str, List[dict]]:
    """
    Load and normalize hooks.json. Returns ``{"PreToolUse": [...], "PostToolUse": [...]}``.

    Missing file, broken JSON, or a wrong top-level shape all mean "no
    hooks" — never an error (hooks are a bonus, not a gate).
    """
    empty: Dict[str, List[dict]] = {"PreToolUse": [], "PostToolUse": []}
    path = hooks_file(workspace)
    if not path.is_file():
        return empty
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return empty
    hooks = data.get("hooks") if isinstance(data, dict) else None
    if not isinstance(hooks, dict):
        return empty
    return {
        "PreToolUse": _normalize_entries(hooks.get("PreToolUse")),
        "PostToolUse": _normalize_entries(hooks.get("PostToolUse")),
    }


def _matching(hook: dict, tool: str) -> bool:
    """Regex fullmatch against the tool name; invalid patterns never match."""
    try:
        return re.fullmatch(hook["matcher"], tool) is not None
    except re.error:
        return False


def _execute(hook: dict, payload: dict) -> Tuple[int, str]:
    """Run one hook command with the JSON payload on stdin. Never raises."""
    cfg = load_config()
    timeout = max(1, min(60, int(hook.get("timeout_sec", DEFAULT_TIMEOUT_SEC))))
    try:
        proc = subprocess.run(
            build_command_argv(hook["command"]),
            cwd=WORKSPACE_DIR,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=json.dumps(payload, ensure_ascii=False, default=str),
            env=_sanitized_environment(),
        )
        return proc.returncode, (proc.stdout or "").strip()
    except subprocess.TimeoutExpired:
        return 124, ""
    except Exception as exc:  # hook infra failure is never fatal
        log.warning("hook execute failed command=%s error=%s", hook.get("command", "?"), exc)
        return 1, ""


def _run(event: str, payload: dict, deny_on_two: bool) -> Optional[str]:
    """Fire every matching hook for an event; returns deny reason / feedback."""
    hooks = load_hooks().get(event) or []
    for hook in hooks:
        if not _matching(hook, str(payload.get("tool", ""))):
            continue
        code, out = _execute(hook, payload)
        if deny_on_two and code == DENY_EXIT_CODE:
            reason = out[:500] or "(tanpa pesan)"
            log.info("hook denied tool=%s reason=%s", payload.get("tool"), reason)
            return reason
        if not deny_on_two and code == 0 and out:
            return out[:2000]
        if code not in (0, DENY_EXIT_CODE):
            log.warning("hook exit=%s event=%s tool=%s", code, event, payload.get("tool"))
    return None


def run_pre_tool_use(tool: str, args: dict) -> Optional[str]:
    """PreToolUse: deny reason string, or None to allow the tool call."""
    return _run("PreToolUse", {"tool": tool, "args": args}, deny_on_two=True)


def run_post_tool_use(tool: str, args: dict, result: Any) -> Optional[str]:
    """PostToolUse: feedback appended to the tool result, or None."""
    preview = str(result)[:RESULT_PREVIEW_CHARS]
    return _run("PostToolUse", {"tool": tool, "args": args, "result": preview}, deny_on_two=False)


def apply_hooks(registry: Dict[str, Callable]) -> Dict[str, Callable]:
    """
    Wrap every tool in a registry with Pre/PostToolUse hooks.

    Denial (exit 2) short-circuits into a ``DIBLOKIR HOOK`` result string
    without executing the tool; post feedback is appended to the result.
    Used by ``effective_tool_registry`` so both provider loops inherit it.
    """
    if not any(load_hooks().values()):
        return registry

    def hooked(name: str, func: Callable) -> Callable:
        def wrapper(**kwargs):
            deny = run_pre_tool_use(name, kwargs)
            if deny is not None:
                return f"DIBLOKIR HOOK (PreToolUse): {deny}"
            try:
                result = func(**kwargs)
            except Exception as exc:
                result = f"Exception saat eksekusi {name}: {str(exc)}"
            feedback = run_post_tool_use(name, kwargs, result)
            if feedback:
                result = f"{result}\n\n[hook PostToolUse] {feedback}"
            return result

        return wrapper

    return {name: hooked(name, func) for name, func in registry.items()}
