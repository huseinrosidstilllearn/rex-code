"""
rex.worker
RexWorker: build-capable sub-agent for delegated implementation tasks.

Unlike the five read-only dinosaur sub-agents (rex.subagents), RexWorker
runs the SAME tools and gates as the main agent in BUILD mode, but its
writes are hard-scoped to the workspace root: any path escaping
``workspace/`` is refused before touching disk.

Safety model (identical posture to the main agent):
- Plan-mode top: when the main agent runs in plan mode, workers are
  refused outright (no build work without the user's build switch).
- Approval gate: worker tool calls go through request_approval(); with a
  UI provider registered, the human approves each destructive action.
  Headless/tests (no provider) fail open — same as the main agent.
- Checkpoints: every worker write snapshots the file first, so /rewind
  restores the workspace exactly as it was before the delegation.
- Recursion guard: workers cannot spawn workers.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from rex.config import WORKSPACE_DIR, get_active_mode
from rex.core import RexAgent

# Workers may ONLY write inside the workspace root (enforced by tools.py
# _is_sensitive whenever a worker delegation is active).
WORKER_WRITE_ROOT = WORKSPACE_DIR

_lock = threading.Lock()
_active_workers = 0


class WorkerScopeError(Exception):
    """A worker tool call attempted to touch a path outside the workspace."""


def _inside_worker() -> bool:
    return _active_workers > 0


class RexWorker:
    """Delegated build worker — build-mode tools, workspace-scoped writes."""

    name = "rex_worker"
    role = "Implementation Worker"
    color = "blue"
    icon_ascii = "  (o.o)\n  /[X]\\"
    web_icon = "/static/icons/brachio.svg"

    system_prompt = (
        "Anda adalah RexWorker, sub-agent implementasi Rex Code. "
        "Tugas Anda MENERAPKAN perubahan kode yang sudah dianalisis/direncanakan: "
        "menulis file baru, mengedit file yang ada (baca dulu, diff minimal via apply_patch), "
        "menjalankan perintah verifikasi, dan melaporkan hasil singkat + file yang diubah. "
        "Semua tulisan HANYA boleh di dalam direktori workspace. "
        "Jika task meminta hal di luar itu, laporkan penolakan. Jangan menebak — verifikasi."
    )

    def __init__(self, max_depth: int = 1):
        self._max_depth = max_depth
        self._depth = 0

    def run(self, task: str, context: str = "") -> str:
        global _active_workers
        if self._depth >= self._max_depth:
            return "[rex_worker] DIBLOKIR: delegasi rekursif tidak diizinkan."
        prev_mode = get_active_mode()
        if prev_mode != "build":
            return (
                "[rex_worker] DITOLAK: worker hanya berjalan saat Rex berada di Mode Build. "
                "Minta pengguna mengaktifkan Mode Build dulu (tulisan file tidak boleh di Mode Plan)."
            )
        self._depth += 1
        with _lock:
            _active_workers += 1
        try:
            agent = RexAgent()
            prompt = (
                f"{self.system_prompt}\n\n"
                f"Context:\n{context}\n\n"
                f"Task:\n{task}\n\n"
                "Laporan akhir: ringkas file yang dibuat/diubah + hasil verifikasi."
            )
            return agent.run(prompt)
        finally:
            with _lock:
                _active_workers -= 1
            self._depth -= 1
            set_active_mode(prev_mode or "plan")


def is_worker_active() -> bool:
    """True while a RexWorker delegation is executing in this process."""
    return _inside_worker()
