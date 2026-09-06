"""
rex.stats
=========
Local session statistics for Rex Code: token usage per session and
aggregated per day/project, plus a rough cost estimate.

Pricing is deliberately a *convention*, not a service: users edit
``config.json -> "model_costs"`` with USD-per-million-token rates for the
models they use. Unknown models simply show 0.00 — never a made-up number.

All data comes from the local session store (JSON files); nothing leaves
the machine.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

from rex.config import load_config, normalize_config
from rex.sessions import session_store

DEFAULT_COSTS = {"default_input_per_m": 0.0, "default_output_per_m": 0.0}


def _model_costs(cfg: Optional[dict] = None) -> Dict[str, Dict[str, float]]:
    """config "model_costs": {"<model name>": {"input": x, "output": y}} (USD per 1M tokens)."""
    try:
        if cfg is None:
            cfg = normalize_config(load_config())
        raw = cfg.get("model_costs")
        if not isinstance(raw, dict):
            return {}
        cleaned: Dict[str, Dict[str, float]] = {}
        for model, rates in raw.items():
            if not isinstance(model, str) or not isinstance(rates, dict):
                continue
            try:
                cleaned[model] = {
                    "input": max(0.0, float(rates.get("input", 0) or 0)),
                    "output": max(0.0, float(rates.get("output", 0) or 0)),
                }
            except (TypeError, ValueError):
                continue
        return cleaned
    except Exception:
        return {}


def _estimate_cost(model: str, prompt: int, completion: int, costs: Dict[str, Dict[str, float]]) -> float:
    """USD estimate for one model's usage; 0.0 when the model has no rates."""
    rates = costs.get(model)
    if not rates:
        return 0.0
    return (prompt / 1_000_000.0) * rates["input"] + (completion / 1_000_000.0) * rates["output"]


def collect_stats(limit: int = 50) -> Dict:
    """
    Aggregate token usage across stored sessions.

    Returns {sessions: [...], totals: {...}, by_day: {...}} where
    sessions is newest-first and includes per-session usage + cost.
    Never raises.
    """
    try:
        cfg = normalize_config(load_config())
        costs = _model_costs(cfg)
        sessions: List[Dict] = []
        totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost_usd": 0.0}
        by_day: Dict[str, Dict[str, float]] = defaultdict(
            lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost_usd": 0.0}
        )
        for meta in session_store.list()[: max(1, limit)]:
            try:
                data = session_store.load(meta["id"])
            except Exception:
                continue
            usage = data.get("usage") or {}
            prompt = int(usage.get("prompt_tokens", 0) or 0)
            completion = int(usage.get("completion_tokens", 0) or 0)
            total = int(usage.get("total_tokens", 0) or 0)
            if total <= 0 and not (prompt or completion):
                total = prompt + completion
            model = str(data.get("model", ""))
            cost = _estimate_cost(model, prompt, completion, costs)
            day = str(data.get("created_at", ""))[:10] or "unknown"
            entry = {
                "id": data.get("id"),
                "title": data.get("title"),
                "created_at": data.get("created_at"),
                "provider": data.get("provider"),
                "model": model,
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": total,
                "cost_usd": cost,
            }
            sessions.append(entry)
            totals["prompt_tokens"] += prompt
            totals["completion_tokens"] += completion
            totals["total_tokens"] += total
            totals["cost_usd"] += cost
            bucket = by_day[day]
            bucket["prompt_tokens"] += prompt
            bucket["completion_tokens"] += completion
            bucket["total_tokens"] += total
            bucket["cost_usd"] += cost
        return {"sessions": sessions, "totals": totals, "by_day": dict(by_day)}
    except Exception:
        return {"sessions": [], "totals": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost_usd": 0.0}, "by_day": {}}


def format_stats(limit: int = 50) -> str:
    """Render /stats output: totals, per-day table, per-session table."""
    data = collect_stats(limit)
    totals = data["totals"]
    lines = ["Statistik pemakaian (lokal)", "=" * 60]
    lines.append(
        f"Total: {totals['total_tokens']:,} token "
        f"(prompt {totals['prompt_tokens']:,} · completion {totals['completion_tokens']:,})"
    )
    lines.append(f"Estimasi biaya: ${totals['cost_usd']:.4f}")

    if data["by_day"]:
        lines.append("")
        lines.append("Per hari:")
        lines.append(f"  {'Tanggal':<12}{'Total':>12}{'Biaya':>12}")
        for day in sorted(data["by_day"], reverse=True)[:14]:
            bucket = data["by_day"][day]
            lines.append(f"  {day:<12}{int(bucket['total_tokens']):>12,}{bucket['cost_usd']:>11.4f}$")

    if data["sessions"]:
        lines.append("")
        lines.append("Sesi terakhir:")
        for entry in data["sessions"][:10]:
            title = (entry["title"] or "")[:34]
            lines.append(
                f"  {entry['model'] or '?':<22}{entry['total_tokens']:>10,}  {title}"
            )
    else:
        lines.append("")
        lines.append("(belum ada sesi tercatat)")
    return "\n".join(lines)
