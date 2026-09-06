"""
rex.review
==========
Session review & safety UX for Rex Code.

- ``session_diff()`` / ``format_session_diff()`` — per-file review of every
  workspace change made during this session, diffed against the shadow git
  (same store that powers checkpoints/undo, so it works in non-git folders).
- ``doctor()`` / ``format_doctor()`` — health check: version, config, API
  keys, provider availability, updater, shadow repo integrity.
- ``run_tests_hook()`` — runs the project's configured test command
  (config "test_hook".command) inside the sandbox. The agent feeds failures
  back into its own loop; ``AUTO_TEST_HOOK`` documents the convention.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from rex.config import load_config, normalize_config
from rex.logging_setup import log

AUTO_TEST_HOOK = (
    "Setelah mengubah file, jalankan test_hook (config 'test_hook'.command) "
    "dan perbaiki kegagalan sebelum melanjutkan."
)


# ──────────────────────────────────────────────────────────────────────
# Session diff (review per-file of the whole session's changes)
# ──────────────────────────────────────────────────────────────────────

def _workspace() -> Path:
    from rex.config import WORKSPACE_DIR
    return Path(WORKSPACE_DIR)


def _shadow_env() -> dict:
    import os
    env = os.environ.copy()
    env["GIT_DIR"] = str(_workspace() / ".rex" / "repo")
    env["GIT_WORK_TREE"] = str(_workspace())
    return env


def session_diff() -> Optional[str]:
    """
    Unified diff of the workspace versus the newest shadow checkpoint
    (everything the session changed since the last automatic snapshot).
    Returns None when the shadow repo has no history yet. Never raises.
    """
    ws = _workspace()
    git_dir = ws / ".rex" / "repo"
    if not (git_dir / "HEAD").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD", "--stat", "--no-color"],
            env=_shadow_env(), cwd=str(ws), capture_output=True, text=True,
            timeout=30, encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            return None
        stat = result.stdout.strip()
        if not stat:
            return ""  # no changes since last checkpoint
        full = subprocess.run(
            ["git", "diff", "HEAD", "--no-color"],
            env=_shadow_env(), cwd=str(ws), capture_output=True, text=True,
            timeout=30, encoding="utf-8", errors="replace",
        )
        return full.stdout if full.returncode == 0 else stat
    except Exception as exc:
        log.debug(f"session diff failed: {exc}")
        return None


def format_session_diff(max_chars: int = 20000) -> str:
    """Human-readable /diff output. '' diff -> friendly empty state."""
    diff = session_diff()
    if diff is None:
        return "(belum ada checkpoint — belum ada perubahan sesi yang bisa direview)"
    if not diff.strip():
        return "(tidak ada perubahan sejak checkpoint terakhir)"
    if len(diff) > max_chars:
        diff = diff[:max_chars] + "\n...[diff dipotong]"
    return diff


# ──────────────────────────────────────────────────────────────────────
# Test hook (auto test-run after BUILD edits)
# ──────────────────────────────────────────────────────────────────────

def run_tests_hook(cfg: Optional[dict] = None, timeout: int = 120) -> Dict:
    """
    Run the configured test command in the workspace (config "test_hook").
    Returns {ran, passed, output, command}; .get() is used everywhere so
    a malformed config can never crash the caller.
    """
    try:
        if cfg is None:
            cfg = normalize_config(load_config())
        hook = cfg.get("test_hook") or {}
        if not isinstance(hook, dict) or not hook.get("enabled", False):
            return {"ran": False, "passed": None, "output": "", "command": ""}
        command = str(hook.get("command") or "").strip()
        if not command:
            return {"ran": False, "passed": None, "output": "", "command": ""}
        try:
            timeout = max(5, int(hook.get("timeout_sec", timeout)))
        except (TypeError, ValueError):
            pass
        from rex.shell import build_command_argv
        result = subprocess.run(
            build_command_argv(command),
            cwd=str(_workspace()), capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
        )
        output = ((result.stdout or "") + (result.stderr or "")).strip()
        return {
            "ran": True,
            "passed": result.returncode == 0,
            "output": output[-4000:],
            "command": command,
        }
    except subprocess.TimeoutExpired:
        return {"ran": True, "passed": False, "output": f"timeout setelah {timeout}s", "command": ""}
    except Exception as exc:
        return {"ran": True, "passed": False, "output": f"error: {exc}", "command": ""}


# ──────────────────────────────────────────────────────────────────────
# Doctor (health check)
# ──────────────────────────────────────────────────────────────────────

def doctor() -> Dict:
    """Collect health signals. Never raises; every check is independent."""
    import os
    import rex
    from rex.providers.manager import get_fallback_chain

    cfg = normalize_config(load_config())
    results: List[Dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        results.append({"name": name, "ok": bool(ok), "detail": detail})

    add("versi", True, f"Rex Code v{rex.__version__} (mode: {cfg.get('active_mode', '?')})")

    provider_id = cfg.get("active_provider", "gemini")
    provider = cfg.get("providers", {}).get(provider_id, {})
    key_env = str(provider.get("api_key_env", ""))
    api_key = os.getenv(key_env, "") if key_env else ""
    masked = (api_key[:4] + "…" + api_key[-3:]) if len(api_key) > 8 else ("< kosong >" if not api_key else "< terlalu pendek >")
    add("api_key", bool(api_key), f"{key_env} = {masked}")

    model = cfg.get("active_model", "?")
    add("provider", bool(provider), f"{provider_id} · model: {model}")

    chain = get_fallback_chain(cfg)
    add("fallback_chain", len(chain) > 1,
        " → ".join(f"{pid}:{model}" for pid, model in chain) if len(chain) > 1
        else "belum dikonfigurasi (config providers_fallback) — provider tunggal")

    key_names = sorted({str(p.get("api_key_env", "")) for p in cfg.get("providers", {}).values() if p.get("api_key_env")})
    missing = [name for name in key_names if not os.getenv(name, "")]
    add("provider_keys", not missing,
        "semua terpasang" if not missing else f"belum di-set: {', '.join(missing)} (opsional)")

    ws = _workspace()
    shadow_ok = (ws / ".rex" / "repo" / "HEAD").exists()
    add("checkpoints", shadow_ok,
        "shadow git aktif" if shadow_ok else "belum ada checkpoint (terbentuk otomatis saat aksi build)")

    hook = cfg.get("test_hook") or {}
    hook_cmd = str(hook.get("command") or "").strip() if isinstance(hook, dict) else ""
    add("test_hook", bool(hook.get("enabled") and hook_cmd),
        f"'{hook_cmd}'" if hook_cmd else "belum diset (config test_hook.command + enabled: true)")

    updates = cfg.get("updates") or {}
    add("auto_update", bool(updates.get("enabled", True)),
        f"repo: {updates.get('repo', '?')} · interval: {updates.get('check_interval_hours', '?')}h")

    approval = cfg.get("approval") or {}
    add("approval", bool(approval.get("enabled", False)),
        "aktif — tool destruktif minta konfirmasi" if approval.get("enabled") else
        "nonaktif (config approval.enabled: true untuk mengaktifkan)")

    return {"results": results, "config": cfg}


def format_doctor() -> str:
    """Render doctor() as a check-mark report."""
    data = doctor()
    lines = ["Rex Doctor — kesehatan instalasi", "-" * 46]
    for item in data["results"]:
        mark = "✔" if item["ok"] else "○"
        lines.append(f"[{mark}] {item['name']:<15} {item['detail']}")
    lines.append("")
    lines.append("(✔ = siap · ○ = belum diset/opsional)")
    return "\n".join(lines)
