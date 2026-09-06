"""
rex.status
==========
``/status`` — one aggregated health report for the whole stack:
version, provider + API keys, MCP servers, plugins, hooks, scheduler,
sessions, checkpoints, updater, approval and the token budget.

Config-level inspection only: nothing is executed and no MCP server is
connected here, so the report is instant and side-effect free. Every
section is independent — a failing one renders as "○", never an error.
"""

from __future__ import annotations

from typing import Dict, List

from rex.config import normalize_config


def collect_status() -> Dict:
    """
    Aggregate status entries from every subsystem. Never raises.

    Returns {"results": [{name, ok, detail}...], "config": <normalized cfg>}.
    """
    from rex.review import doctor

    base = doctor()
    cfg = base["config"]
    results: List[Dict] = base["results"]
    results = list(results)

    def add(name: str, ok: bool, detail: str) -> None:
        results.append({"name": name, "ok": bool(ok), "detail": detail})

    # ── MCP servers (config view; no connection attempt) ─────────────
    mcp = cfg.get("mcp") or {}
    servers = mcp.get("servers") or {}
    if not mcp.get("enabled", True):
        add("mcp", False, "nonaktif (config mcp.enabled)")
    elif servers:
        summary = ", ".join(
            f"{name}[{'cmd' if entry.get('command') else 'http'}]"
            for name, entry in sorted(servers.items())
        )
        add("mcp", True, f"{len(servers)} server: {summary}")
    else:
        add("mcp", False, "belum ada server (config mcp.servers)")

    # ── Plugins (discovered files + config list) ──────────────────────
    try:
        from rex.plugins import _discover_plugin_files
        files = [p.stem for p in _discover_plugin_files()]
    except Exception:
        files = []
    configured = [str(item) for item in (cfg.get("plugins") or {}).get("list") or []]
    if files:
        extra = f" +{len(configured)} di config" if configured else ""
        add("plugins", True, f"{len(files)} terpasang: {', '.join(files)}{extra}")
    elif configured:
        add("plugins", True, f"{len(configured)} dari config: {', '.join(configured)}")
    else:
        add("plugins", False, "belum ada (rex plugin add <git-url> atau plugins/)")

    # ── Hooks (Pre/PostToolUse) ───────────────────────────────────────
    try:
        from rex.hooks import load_hooks
        hooks = load_hooks()
        pre, post = len(hooks.get("PreToolUse") or []), len(hooks.get("PostToolUse") or [])
    except Exception:
        pre = post = 0
    add("hooks", bool(pre or post),
        f"PreToolUse: {pre} · PostToolUse: {post}" if (pre or post)
        else "belum ada (.rex/hooks.json)")

    # ── Scheduler jobs ────────────────────────────────────────────────
    scheduler = cfg.get("scheduler") or {}
    jobs = scheduler.get("jobs") or []
    enabled = sum(1 for job in jobs if job.get("enabled"))
    add("scheduler", scheduler.get("enabled", True) and bool(enabled),
        f"{len(jobs)} job ({enabled} aktif)" if jobs else
        "belum ada job (config scheduler.jobs)")

    # ── Sessions ──────────────────────────────────────────────────────
    try:
        from rex.sessions import session_store
        sessions = session_store.list()
    except Exception:
        sessions = []
    if sessions:
        latest = sessions[0]
        add("sessions", True,
            f"{len(sessions)} tersimpan · terakhir: '{(latest.get('title') or '')[:32]}' "
            f"({(latest.get('updated_at') or '')[:16]})")
    else:
        add("sessions", False, "belum ada sesi tersimpan")

    # ── Token budget ──────────────────────────────────────────────────
    budget = cfg.get("token_budget", 0) or 0
    add("budget", bool(budget),
        f"{budget:,} token per sesi" if budget
        else "tidak dibatasi (config token_budget, 0 = off)")

    return {"results": results, "config": cfg}


def format_status() -> str:
    """Render /status as a check-mark report grouped like /doctor."""
    data = collect_status()
    lines = ["Rex Status — ringkasan seluruh subsistem", "-" * 46]
    for item in data["results"]:
        mark = "✔" if item["ok"] else "○"
        lines.append(f"[{mark}] {item['name']:<15} {item['detail']}")
    lines.append("")
    lines.append("(✔ = aktif/siap · ○ = belum diset/opsional)")
    return "\n".join(lines)
