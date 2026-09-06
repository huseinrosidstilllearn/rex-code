"""
rex.export
==========
``/export`` — write a stored session to a portable file.

- ``md``   : clean Markdown transcript (default)
- ``html`` : standalone HTML with inline CSS, no external assets

Files land in ``<workspace>/exports/`` as
``rex-<session8>-<YYYYmmdd-HHMMSS>.<ext>``. Content is the already-
redacted session record, so secrets stay redacted in exports. Usage
totals come from the same model_costs convention as /stats.
"""

from __future__ import annotations

import html as html_mod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from rex.logging_setup import log
from rex.stats import _estimate_cost, _model_costs
from rex.config import load_config, normalize_config

EXPORT_DIRNAME = "exports"
MAX_MESSAGE_CHARS = 100_000

ROLE_LABELS_MD = {"user": "You", "assistant": "Rex", "tool": "Tool"}


def _export_dir(out_dir: Optional[Path] = None) -> Path:
    if out_dir is not None:
        directory = Path(out_dir)
    else:
        from rex.config import WORKSPACE_DIR
        directory = Path(WORKSPACE_DIR) / EXPORT_DIRNAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def export_path(session_id: str, fmt: str, out_dir: Optional[Path] = None) -> Path:
    """Deterministic filename for one export."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return _export_dir(out_dir) / f"rex-{str(session_id)[:8]}-{stamp}.{fmt}"


def _usage_line(data: Dict[str, Any], costs: Dict[str, Dict[str, float]]) -> str:
    usage = data.get("usage") or {}
    prompt = int(usage.get("prompt_tokens", 0) or 0)
    completion = int(usage.get("completion_tokens", 0) or 0)
    total = usage.get("total_tokens")
    total = int(total) if total is not None else prompt + completion
    cost = _estimate_cost(str(data.get("model") or ""), prompt, completion, costs)
    return (
        f"Token: {total:,} (prompt {prompt:,} · completion {completion:,}) · "
        f"Estimasi biaya: ${cost:.4f}"
    )


def _message_lines(data: Dict[str, Any]) -> list:
    """Normalized [(role, text)] in conversation order."""
    lines = []
    for message in data.get("messages") or []:
        role = str(message.get("role") or "?")
        content = str(message.get("content") or "").strip()
        name = message.get("name")
        if role == "tool" and name:
            content = f"[tool {name}] {content}"
        if content:
            lines.append((role, content[:MAX_MESSAGE_CHARS]))
    return lines


def build_markdown(data: Dict[str, Any], costs: Dict[str, Dict[str, float]]) -> str:
    """Markdown transcript of one session record."""
    lines = [
        f"# {data.get('title') or 'Percakapan Rex'}",
        "",
        f"- Sesi: `{data.get('id')}`",
        f"- Dibuat: {str(data.get('created_at'))[:19]}",
        f"- Provider: {data.get('provider')} · Model: {data.get('model')}",
        "",
        "---",
        "",
    ]
    for role, text in _message_lines(data):
        label = ROLE_LABELS_MD.get(role, role)
        lines.append(f"## {label}")
        lines.append("")
        if role == "tool":
            lines.append("```")
            lines.append(text)
            lines.append("```")
        else:
            lines.append(text)
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"_{_usage_line(data, costs)}_")
    return "\n".join(lines) + "\n"


_HTML_SHELL = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ font-family: -apple-system, 'Segoe UI', Roboto, sans-serif; max-width: 860px;
         margin: 2rem auto; padding: 0 1rem; color: #18181b; background: #fafafa; }}
  h1 {{ font-size: 1.4rem; }} h2 {{ font-size: 0.8rem; text-transform: uppercase;
       letter-spacing: 0.08em; color: #71717a; margin-bottom: 0.2rem; }}
  .msg {{ border: 1px solid #e4e4e7; border-radius: 8px; padding: 0.7rem 1rem;
          margin: 0.6rem 0; background: #fff; }}
  .tool pre {{ background: #18181b; color: #e4e4e7; padding: 0.6rem; border-radius: 6px;
               overflow-x: auto; font-size: 0.85em; }}
  .meta {{ color: #71717a; font-size: 0.85rem; }}
  footer {{ margin-top: 2rem; color: #71717a; font-size: 0.85rem; border-top: 1px solid #e4e4e7;
            padding-top: 0.6rem; }}
</style>
</head>
<body>
<h1>{title}</h1>
<p class="meta">Sesi <code>{sid}</code> · {created} · {provider} / {model}</p>
{body}
<footer>{usage}</footer>
</body>
</html>
"""


def build_html(data: Dict[str, Any], costs: Dict[str, Dict[str, float]]) -> str:
    """Standalone HTML transcript (inline CSS, nothing external)."""
    blocks = []
    for role, text in _message_lines(data):
        escaped = html_mod.escape(text)
        if role == "tool":
            blocks.append(
                f'<div class="msg tool"><h2>{html_mod.escape(ROLE_LABELS_MD.get(role, role))}</h2>'
                f"<pre>{escaped}</pre></div>"
            )
        else:
            blocks.append(
                f'<div class="msg {html_mod.escape(role)}"><h2>'
                f"{html_mod.escape(ROLE_LABELS_MD.get(role, role))}</h2>"
                f"<p>{escaped.replace(chr(10), '<br>')}</p></div>"
            )
    return _HTML_SHELL.format(
        title=html_mod.escape(str(data.get("title") or "Percakapan Rex")),
        sid=html_mod.escape(str(data.get("id") or "")),
        created=html_mod.escape(str(data.get("created_at"))[:19]),
        provider=html_mod.escape(str(data.get("provider") or "?")),
        model=html_mod.escape(str(data.get("model") or "?")),
        body="\n".join(blocks),
        usage=html_mod.escape(_usage_line(data, costs)),
    )


def export_session(session_id: str, fmt: str = "md", out_dir: Optional[Path] = None) -> str:
    """
    Export one stored session. Returns a human-readable result line
    (path on success, error text otherwise). Never raises.
    """
    fmt = str(fmt or "md").strip().lower().lstrip(".")
    if fmt not in ("md", "html"):
        return f"Error: format '{fmt}' tidak dikenal — gunakan 'md' atau 'html'."
    try:
        from rex.sessions import session_store
        data = session_store.load(session_id)
    except Exception as exc:
        return f"Error: sesi tidak bisa dimuat ({type(exc).__name__})."
    try:
        costs = _model_costs(normalize_config(load_config()))
    except Exception:
        costs = {}
    try:
        builder = build_html if fmt == "html" else build_markdown
        target = export_path(session_id, fmt, out_dir)
        target.write_text(builder(data, costs), encoding="utf-8")
        log.info("session exported id=%s fmt=%s path=%s", session_id, fmt, target)
        return f"Diekspor ke {target}"
    except Exception as exc:
        return f"Error menulis ekspor: {type(exc).__name__}: {str(exc)[:200]}"
