"""
rex.agentguard
Tool-call hygiene for the agent loops: detects identical repeated tool
calls (wasted work / model loops) and nudges the model to change strategy.

Works for BOTH provider loops:
- Router loop (rex.core._router_round): guard checked before executing.
- Gemini native AFC loop (rex.providers.gemini._build_wrapped_tool): the
  wrapper consults the active guard before invoking the real tool.

The guard is activated per RexAgent.run() via a ContextVar so nested
agents (sub-agents) each get an isolated counter and thread workers are
tracked correctly.
"""

import contextvars
import hashlib
import json
from typing import Any, Dict, Optional, Tuple

# An identical call (same name + same args) is executed this many times
# before the guard replaces the next identical repeat with a warning.
REPEAT_THRESHOLD = 3

# Tools whose identical re-invocation is LEGITIMATE because the result
# depends on external/world state that can change between calls
# (re-running tests after an edit, polling a background task, git state,
# live web content). The guard never interferes with these.
EXEMPT_TOOLS = frozenset({
    "run_command",       # re-verify after edits — identical args, new outcome
    "run_command_bg",
    "task_output",       # background task progress evolves over time
    "task_kill",
    "git_status",
    "web_search",
    "web_fetch",
})

WARNING_TEMPLATE = (
    "[GUARD] Panggilan {name} dengan argumen yang sama persis sudah dijalankan "
    "{previous}x dan hasilnya pasti sama. Jangan mengulangi panggilan identik. "
    "Ubah pendekatan: perbaiki argumen, gunakan tool lain, pecah masalahnya, "
    "atau laporkan kendala Anda kepada pengguna."
)


class ToolCallGuard:
    """Counts identical tool calls and warns on wasteful repeats."""

    def __init__(self, threshold: int = REPEAT_THRESHOLD):
        self.threshold = max(2, int(threshold))
        self._counts: Dict[str, int] = {}
        # Stats surfaced in logs/tests.
        self.blocked = 0

    @staticmethod
    def _key(name: str, args: Dict[str, Any]) -> str:
        try:
            payload = json.dumps(
                {"name": str(name), "args": args}, sort_keys=True, default=str
            )
        except Exception:
            payload = f"{name}|{args!r}"
        return hashlib.sha256(payload.encode("utf-8", "replace")).hexdigest()

    def observe(self, name: str, args: Dict[str, Any]) -> Optional[str]:
        """
        Register one tool call.

        Returns a warning string when this exact call was already executed
        ``threshold - 1`` times (this one would be a wasted repeat), else
        None (the call should proceed normally).

        State-dependent tools (EXEMPT_TOOLS: run_command, task_output, ...)
        are never guarded — identical re-runs there are legitimate
        verification/polling, not loops.
        """
        if str(name) in EXEMPT_TOOLS:
            return None
        key = self._key(name, args)
        seen = self._counts.get(key, 0) + 1
        if seen >= self.threshold:
            # Reset the counter so the model can retry the identical call
            # once more later (after reflecting on the warning), but every
            # threshold-th identical attempt stays guarded.
            self._counts[key] = 0
            self.blocked += 1
            return WARNING_TEMPLATE.format(name=name, previous=seen - 1)
        self._counts[key] = seen
        return None


_current_guard: contextvars.ContextVar[Optional[ToolCallGuard]] = contextvars.ContextVar(
    "rex_tool_call_guard", default=None
)


def activate_guard(threshold: int = REPEAT_THRESHOLD) -> Tuple[ToolCallGuard, object]:
    """Install a fresh guard for this run. Returns (guard, token)."""
    guard = ToolCallGuard(threshold)
    token = _current_guard.set(guard)
    return guard, token


def deactivate_guard(token: object) -> None:
    """Restore the previous guard (supports nested agents)."""
    try:
        _current_guard.reset(token)
    except Exception:
        pass


def active_guard() -> Optional[ToolCallGuard]:
    """The guard for the current run context, if any."""
    return _current_guard.get()
