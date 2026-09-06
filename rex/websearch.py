"""
rex.websearch
=============
``web_search`` + ``web_fetch`` — read-only research tools with guardrails.

- ``web_search``: DuckDuckGo HTML endpoint (no API key, no new dependency);
  returns titles, links and snippets.
- ``web_fetch``: downloads one page and returns readable text.

Guardrails (keamanan tidak pernah mundur):

- http/https only; private, link-local and internal-suffix hosts are
  blocked (SSRF / cloud-metadata protection).
- config ``web.allowed_domains``: when set, only these domains (exact or
  subdomain) are fetchable; empty means the open web.
- every response body is secret-redacted (key/token-shaped strings and
  live environment values) and size-capped before it reaches the model.
- both tools are approval-gateable via the actions ``web_search`` /
  ``web_fetch`` and work in PLAN & BUILD (read-only).
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from rex.config import load_config, normalize_config
from rex.logging_setup import log
from rex.approval import request_approval, summarize_action

USER_AGENT = "RexCode-Agent/0.3 (+https://github.com/huseinrosidstilllearn/rex-code)"
MAX_RESULTS = 8
DEFAULT_TIMEOUT = 15
DEFAULT_MAX_CHARS = 8000

PRIVATE_HOST_PATTERNS = (
    re.compile(r"^localhost$", re.IGNORECASE),
    re.compile(r"^127\."),                                  # loopback
    re.compile(r"^10\."),                                   # private
    re.compile(r"^192\.168\."),                             # private
    re.compile(r"^172\.(1[6-9]|2\d|3[01])\."),              # private
    re.compile(r"^169\.254\."),                             # link-local / metadata
    re.compile(r"^0\.0\.0\.0$|^::1$|^\[::1\]$|^::$"),       # unspecified / v6 loopback
    re.compile(r"^fe80:", re.IGNORECASE),                   # v6 link-local
    re.compile(r"^fd[0-9a-f]{2}:", re.IGNORECASE),          # v6 unique-local
)
INTERNAL_SUFFIXES = (".local", ".internal", ".lan", ".home", ".corp", ".intranet")

# Key/token-shaped strings that must never leak through fetched content.
SECRET_SHAPES = (
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AIza[A-Za-z0-9_\-]{30,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
)


def web_settings(cfg: Optional[dict] = None) -> Dict:
    """Normalized "web" section from config.json (never raises)."""
    try:
        if cfg is None:
            cfg = normalize_config(load_config())
        web = cfg.get("web") or {}
        return {
            "enabled": bool(web.get("enabled", True)),
            "allowed_domains": [str(d).lower().strip() for d in web.get("allowed_domains") or [] if str(d).strip()],
            "timeout_sec": max(5, min(60, int(web.get("timeout_sec", DEFAULT_TIMEOUT)))),
            "max_chars": max(500, min(50000, int(web.get("max_chars", DEFAULT_MAX_CHARS)))),
        }
    except Exception:
        return {"enabled": True, "allowed_domains": [], "timeout_sec": DEFAULT_TIMEOUT, "max_chars": DEFAULT_MAX_CHARS}


def redact_secrets(text: str) -> str:
    """Strip key/token-shaped strings and live env secret values."""
    for pattern in SECRET_SHAPES:
        text = pattern.sub("<REDACTED>", text)
    # marker=value pairs (api_key=..., Authorization: Bearer ... etc.)
    from rex.approval import SECRET_MARKERS
    text = re.compile(
        r"(?:" + "|".join(SECRET_MARKERS) + r")['\"\s:=]+[A-Za-z0-9_\-./+]{8,}",
        re.IGNORECASE,
    ).sub("<REDACTED>", text)
    # exact values of secret-named environment variables
    for env_key, secret in os.environ.items():
        if any(marker in env_key.upper() for marker in SECRET_MARKERS) and len(secret) >= 8:
            text = text.replace(secret, "<REDACTED>")
    return text


def _is_private_host(host: str) -> bool:
    host = (host or "").strip()
    if any(pattern.match(host) for pattern in PRIVATE_HOST_PATTERNS):
        return True
    lower = host.lower()
    return any(lower.endswith(suffix) for suffix in INTERNAL_SUFFIXES)


def _unwrap_ddg_href(href: str) -> str:
    """DuckDuckGo wraps results in /l/?uddg=<encoded>; unwrap when present."""
    if "//duckduckgo.com/l/" in href or href.startswith("/l/"):
        parsed = urlparse(href if href.startswith("http") else "https://duckduckgo.com" + href)
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        return unquote(target) if target else href
    return href


def host_allowed(url: str, allowed_domains: List[str]) -> bool:
    """Empty allowlist = open web; otherwise exact host or subdomain match."""
    if not allowed_domains:
        return True
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    return any(host == domain or host.endswith("." + domain) for domain in allowed_domains)


def _check_url(url: str) -> Tuple[Optional[str], str]:
    """Common guards. Returns (error, host)."""
    try:
        parsed = urlparse(str(url or "").strip())
    except Exception:
        return "URL tidak valid.", ""
    host = parsed.hostname or ""
    if parsed.scheme not in ("http", "https"):
        return f"DIBLOKIR: hanya http/https yang diizinkan (dapat: {parsed.scheme or '?'}).", host
    if _is_private_host(host):
        return f"DIBLOKIR: host internal/tidak publik ('{host}').", host
    allowed = web_settings()["allowed_domains"]
    if not host_allowed(url, allowed):
        return (
            "DIBLOKIR: domain tidak ada di web.allowed_domains "
            f"({', '.join(allowed) or 'kosong'}).", host
        )
    return None, host


def _http_get(url: str, timeout: int) -> Tuple[int, str]:
    import httpx
    response = httpx.get(
        url,
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en,id"},
    )
    return response.status_code, response.text


def web_fetch(url: str) -> str:
    """Ambil isi satu halaman web sebagai teks (aktif di PLAN & BUILD)."""
    error, _ = _check_url(url)
    if error:
        return error
    settings = web_settings()
    if not request_approval("web_fetch", summarize_action("web_fetch", {"url": url})):
        return "DITOLAK PENGGUNA: web_fetch tidak disetujui. Jangan coba lagi tanpa instruksi baru."

    try:
        status, body = _http_get(str(url).strip(), settings["timeout_sec"])
    except Exception as exc:
        return f"Error fetch: {type(exc).__name__}: {str(exc)[:200]}"
    if status != 200:
        return f"Error: HTTP {status} untuk {url}."
    body = redact_secrets(body)
    return _truncate(_extract_text(body, str(url)), settings["max_chars"])


def _extract_text(html: str, url: str) -> str:
    """Very small HTML→text pass: title + visible text, tags stripped."""
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""
    body = re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", html)
    body = re.sub(r"(?is)<br\s*/?>|</p>|</div>|</li>|</h[1-6]>|</tr>", "\n", body)
    body = re.sub(r"(?s)<[^>]+>", " ", body)
    import html as html_mod
    try:
        body = html_mod.unescape(body)
    except Exception:
        pass
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in body.splitlines()]
    body = "\n".join(line for line in lines if line)
    header = f"[{title}] ({url})\n\n" if title else f"({url})\n\n"
    return header + body.strip()


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 20)] + "\n\n[OUTPUT DIPOTONG]"


def _ddg_search(query: str, timeout: int) -> str:
    import httpx
    response = httpx.post(
        "https://html.duckduckgo.com/html/",
        data={"q": query},
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
    )
    if response.status_code != 200:
        return f"Error: mesin pencari menjawab HTTP {response.status_code}."
    return response.text


_RESULT_RE = re.compile(
    r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_SNIPPET_RE = re.compile(
    r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)


def web_search(query: str) -> str:
    """Cari di web via DuckDuckGo (tanpa API key). Aktif di PLAN & BUILD."""
    if not isinstance(query, str) or not query.strip():
        return "Error: query kosong."
    settings = web_settings()
    if not settings["enabled"]:
        return "DIBLOKIR: web_search nonaktif (config web.enabled)."
    if not request_approval("web_search", summarize_action("web_search", {"query": query})):
        return "DITOLAK PENGGUNA: web_search tidak disetujui. Jangan coba lagi tanpa instruksi baru."
    try:
        html = _ddg_search(query.strip()[:400], settings["timeout_sec"])
    except Exception as exc:
        return f"Error search: {type(exc).__name__}: {str(exc)[:200]}"
    return _render_results(html, settings["max_chars"])


def _render_results(html: str, max_chars: int) -> str:
    html = redact_secrets(html)
    tags_re = re.compile(r"<[^>]+>")
    titles = [tags_re.sub("", m.group(2)).strip() for m in _RESULT_RE.finditer(html)]
    links = [_unwrap_ddg_href(m.group(1)) for m in _RESULT_RE.finditer(html)]
    snippets = [tags_re.sub("", m.group(1)).strip() for m in _SNIPPET_RE.finditer(html)]
    lines: List[str] = []
    for index, (title, link) in enumerate(zip(titles, links)):
        if not title or not link.startswith("http"):
            continue
        entry = f"{len(lines) + 1}. {title}\n   {link}"
        if index < len(snippets) and snippets[index]:
            entry += f"\n   {snippets[index][:200]}"
        lines.append(entry)
        if len(lines) >= MAX_RESULTS:
            break
    if not lines:
        return "(tidak ada hasil — coba query lain)"
    return "\n\n".join(lines)[:max_chars]
