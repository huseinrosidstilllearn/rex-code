"""
rex.subagents
Sub-agent framework for Rex Code.
Provides specialized dinosaur sub-agents operating in read-only (Plan) mode,
plus parallel delegation in isolated git worktrees: each delegate gets its
own worktree copy, runs as a headless Rex child (BUILD writes only touch the
copy), and its patch is handed back for the parent to apply behind the
normal approval gate.
"""

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from rex.config import get_active_mode, set_active_mode
from rex.core import RexAgent
from rex.approval import request_approval, summarize_action
from rex import autogit

MAX_PARALLEL_TASKS = 3
CHILD_TIMEOUT_SEC = 600
MAX_CHILD_RESPONSE_CHARS = 6000
MAX_DIFF_CHARS = 4000


class SubAgent:
    """Base class for specialized Rex Code sub-agents."""
    name: str = "generic"
    role: str = "Generic Sub-Agent"
    color: str = "green"
    icon_ascii: str = "  (o.o)\n  /(_)\\"
    web_icon: str = "/static/icons/brachio.svg"
    system_prompt: str = "You are a sub-agent of Rex Code."

    def __init__(self, max_depth: int = 1):
        self._max_depth = max_depth
        self._depth = 0

    def run(self, task: str, context: str = "") -> str:
        if self._depth >= self._max_depth:
            return f"[{self.name}] DIBLOKIR: delegasi rekursif tidak diizinkan."
        self._depth += 1
        prev_mode = get_active_mode()
        # Sub-agents operate strictly in read-only plan mode
        set_active_mode("plan")
        try:
            agent = RexAgent()
            prompt = (
                f"You are {self.name}, {self.role} in Rex Code.\n"
                f"System Directive:\n{self.system_prompt}\n\n"
                f"Context:\n{context}\n\n"
                f"Task:\n{task}"
            )
            return agent.run(prompt)
        finally:
            set_active_mode(prev_mode or "plan")
            self._depth -= 1


class BrachioAgent(SubAgent):
    name = "brachio"
    role = "Code Reviewer & General Analyzer"
    color = "green"
    icon_ascii = r"  _\_/\\n ( o o )\\n  (_/\_"
    web_icon = "/static/icons/brachio.svg"
    system_prompt = (
        "You are Brachio, the long-necked analysis sub-agent. "
        "Review code, evaluate quality, find logical gaps, and propose robust solutions. "
        "You operate in read-only plan mode; do not attempt to write or modify files directly."
    )


class RaptorAgent(SubAgent):
    name = "raptor"
    role = "Bug Hunter & Traceback Specialist"
    color = "yellow"
    icon_ascii = "  /\\_/\\\n ( o.o )\n  > ^ <"
    web_icon = "/static/icons/raptor.svg"
    system_prompt = (
        "You are Raptor, the agile bug-hunting sub-agent. "
        "Analyze tracebacks, locate root causes of runtime errors, and diagnose faulty logic. "
        "Operate strictly in read-only plan mode."
    )


class TrikeAgent(SubAgent):
    name = "trike"
    role = "Security Auditor & Vulnerability Scanner"
    color = "red"
    icon_ascii = "  /▲▲▲\\\n ( ⊙.⊙ )\n  ---v---"
    web_icon = "/static/icons/trike.svg"
    system_prompt = (
        "You are Trike, the armored security audit sub-agent. "
        "Scan code for hardcoded secrets, injection vectors, unsafe practices, and vulnerabilities. "
        "Operate strictly in read-only plan mode."
    )


class PteroAgent(SubAgent):
    name = "ptero"
    role = "Architecture & Documentation Specialist"
    color = "cyan"
    icon_ascii = "  /\\~/\\\\/\n ( o-o )\n  v---v"
    web_icon = "/static/icons/ptero.svg"
    system_prompt = (
        "You are Ptero, the flying architecture and documentation sub-agent. "
        "Review project structure, module dependencies, and draft comprehensive technical documentation. "
        "Operate strictly in read-only plan mode."
    )


class DiloAgent(SubAgent):
    name = "dilo"
    role = "Quality & Anti-Slop Auditor"
    color = "magenta"
    icon_ascii = "  /|~~|\\\n ( o_o )\n  (:::)"
    web_icon = "/static/icons/dilo.svg"
    system_prompt = (
        "You are Dilo, the quality and AI-slop auditing sub-agent. "
        "Detect verbose boilerplate, redundant comments, AI buzzword fluff, and poor maintainability. "
        "Operate strictly in read-only plan mode."
    )


SUBAGENTS: Dict[str, SubAgent] = {
    "brachio": BrachioAgent(),
    "raptor": RaptorAgent(),
    "trike": TrikeAgent(),
    "ptero": PteroAgent(),
    "dilo": DiloAgent(),
}


def get_subagent(name: str) -> Optional[SubAgent]:
    return SUBAGENTS.get(name.lower())


# ────────────────────────────────────────────────────────────────────
# Parallel delegation via git worktrees
# ────────────────────────────────────────────────────────────────────

def _child_command(prompt: str) -> List[str]:
    """Headless one-shot child: frozen exe or source cli.py."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "-p", prompt, "--json"]
    cli_path = Path(__file__).resolve().parent.parent / "cli.py"
    return [sys.executable, str(cli_path), "-p", prompt, "--json"]


def _spawn_child(prompt: str, worktree: Path, timeout: int) -> tuple:
    """Run one headless child inside the worktree. Returns (returncode, stdout)."""
    env = dict(os.environ)
    env["REX_WORKSPACE"] = str(worktree)
    # Child config parity: provider settings + .env API keys copied in.
    from rex.config import CONFIG_FILE, ENV_FILE
    try:
        if CONFIG_FILE.exists():
            shutil.copy2(CONFIG_FILE, worktree / "config.json")
        if ENV_FILE.exists():
            shutil.copy2(ENV_FILE, worktree / ".env")
    except OSError:
        pass  # child falls back to defaults + inherited env
    completed = subprocess.run(
        _child_command(prompt),
        cwd=str(worktree), capture_output=True, text=True,
        timeout=timeout, env=env, encoding="utf-8", errors="replace",
    )
    return completed.returncode, completed.stdout


def run_worktree_delegates(tasks: List[Dict[str, str]], timeout_sec: int = CHILD_TIMEOUT_SEC) -> List[Dict[str, Any]]:
    """
    Run delegates in parallel, each inside its own git worktree.

    Every task is ``{"agent": <name>, "task": <text>}``. Each delegate
    runs as a headless Rex child confined to its worktree (writes never
    touch the user's workspace); afterwards the worktree is removed and
    its diff is returned so the parent can review and apply it through
    ``apply_patch`` (approval gate + checkpoint). Max 3 tasks; requires
    a git repo. Never raises.
    """
    import threading

    tasks = list(tasks or [])[:MAX_PARALLEL_TASKS]
    if not tasks:
        return [{"agent": "?", "task": "", "response": "", "diff": "", "error": "tidak ada tugas"}]

    summary_parts = [f"{t.get('agent', '?')}:{str(t.get('task', ''))[:40]}" for t in tasks]
    if not request_approval("delegate_parallel", summarize_action("delegate_parallel", {"tasks": "; ".join(summary_parts)})):
        return [
            {"agent": t.get("agent", "?"), "task": t.get("task", ""), "response": "", "diff": "",
             "error": "DITOLAK PENGGUNA: delegasi paralel tidak disetujui."}
            for t in tasks
        ]

    if not autogit.is_git_repo():
        return [
            {"agent": t.get("agent", "?"), "task": t.get("task", ""), "response": "", "diff": "",
             "error": "Bukan repo git — delegasi worktree butuh git."}
            for t in tasks
        ]

    results: List[Dict[str, Any]] = [None] * len(tasks)  # type: ignore[list-item]

    def run_one(index: int, item: Dict[str, str]) -> None:
        agent_name = str(item.get("agent", "")).strip().lower()
        task_text = str(item.get("task", "")).strip()
        entry: Dict[str, Any] = {
            "agent": agent_name, "task": task_text,
            "response": "", "diff": "", "error": None,
        }
        sub = get_subagent(agent_name)
        if sub is None:
            entry["error"] = f"Sub-agent '{agent_name}' tidak dikenal."
            results[index] = entry
            return
        if not task_text:
            entry["error"] = "Tugas kosong."
            results[index] = entry
            return
        task_id = f"{agent_name}-{uuid.uuid4().hex[:6]}"
        worktree = autogit.create_worktree(task_id)
        if worktree is None:
            entry["error"] = "Gagal membuat worktree."
            results[index] = entry
            return
        try:
            prompt = f"{sub.system_prompt}\n\nTugas:\n{task_text}"
            code, stdout = _spawn_child(prompt, worktree, max(30, int(timeout_sec)))
            if code != 0:
                entry["error"] = f"Child process gagal (exit {code})."
            try:
                payload = json.loads(stdout.strip() or "{}")
                entry["response"] = str(payload.get("response", ""))[:MAX_CHILD_RESPONSE_CHARS]
                if payload.get("ok") is False and payload.get("error"):
                    entry["error"] = str(payload["error"])[:300]
            except (ValueError, AttributeError):
                if not entry["error"]:
                    entry["error"] = "Output child tidak bisa diparse."
            entry["diff"] = autogit.worktree_diff(task_id)[:MAX_DIFF_CHARS]
        except subprocess.TimeoutExpired:
            entry["error"] = f"Timeout setelah {timeout_sec} detik."
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        finally:
            autogit.remove_worktree(task_id)
            results[index] = entry

    threads = [threading.Thread(target=run_one, args=(i, t), daemon=True) for i, t in enumerate(tasks)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=max(30, int(timeout_sec)) + 30)
    return results
