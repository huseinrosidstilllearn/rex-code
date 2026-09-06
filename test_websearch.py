"""Self-check web tools (rex/websearch.py). Run: python test_websearch.py"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rex.websearch import (
    _extract_text,
    _is_private_host,
    _render_results,
    _unwrap_ddg_href,
    host_allowed,
    redact_secrets,
    web_fetch,
    web_search,
    web_settings,
)


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


DDG_HTML = """
<div class="result">
<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python.org%2F3%2F&rut=abc">Python <b>docs</b></a>
<a class="result__snippet" href="#">Official Python <b>docs</b> site</a>
<a class="result__a" href="https://example.com/guide">Example Guide</a>
<a class="result__a" href="ftp://nope.example/x">Bad Link</a>
</div>
"""

PAGE_HTML = """
<html><head><title>Kerja API — Panduan</title><style>x{}</style></head>
<body>
<script>alert("secret sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456")</script>
<h1>Kerja API</h1><p>Langkah  pertama.</p>
<p>key sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456 di sini</p>
</body></html>
"""


def cfg_patches(over=None):
    cfg = {"active_provider": "gemini", "active_model": "m1", "web": {"enabled": True, "allowed_domains": [], "timeout_sec": 15, "max_chars": 8000, **(over or {})}}
    return [
        patch("rex.websearch.load_config", return_value=cfg),
        patch("rex.websearch.normalize_config", side_effect=lambda c: c),
    ]


def main():
    # ── 1. private/internal host blocking ────────────────────────────
    for host in ("localhost", "127.0.0.1", "10.1.2.3", "192.168.1.5", "172.16.0.9", "172.31.255.1",
                 "169.254.169.254", "0.0.0.0", "::1", "[::1]", "fe80::1", "fd00::9",
                 "box.local", "svc.internal", "my.lan", "x.corp"):
        check(f"private blocked: {host}", _is_private_host(host))
    for host in ("example.com", "docs.python.org", "8.8.8.8", "api.openai.com"):
        check(f"public allowed: {host}", not _is_private_host(host))

    # ── 2. domain allowlist semantics ────────────────────────────────
    check("empty allowlist = open web", host_allowed("https://anything.example/x", []))
    allow = ["example.com"]
    check("exact match", host_allowed("https://example.com/x", allow))
    check("subdomain match", host_allowed("https://api.example.com/x", allow))
    check("other domain denied", not host_allowed("https://notexample.com/x", allow))
    check("suffix trick denied", not host_allowed("https://evilexample.com/x", allow))
    check("scheme denied before allowlist", host_allowed("", ["x"]) is False)

    # ── 3. web_fetch URL guards (no network) ─────────────────────────
    p1, p2 = cfg_patches()
    with p1, p2:
        check("ftp blocked", "hanya http/https" in web_fetch("ftp://example.com/f"))
        check("metadata blocked", "internal/tidak publik" in web_fetch("http://169.254.169.254/latest/meta-data"))
        check("localhost blocked", "internal/tidak publik" in web_fetch("http://localhost:8080/admin"))
        check("empty url blocked", "DIBLOKIR" in web_fetch(""))

    p1, p2 = cfg_patches({"allowed_domains": ["example.com"]})
    with p1, p2:
        check("allowlist denies other domain", "web.allowed_domains" in web_fetch("https://python.org"))
    p1, p2 = cfg_patches({"allowed_domains": ["example.com"]})
    with p1, p2:
        check("allowlist admits listed domain", "Error fetch" in web_fetch("https://example.com/x") or "HTTP" in web_fetch("https://example.com/x"))

    # ── 4. redaction ─────────────────────────────────────────────────
    text = "token ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456 and sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456 plus api_key=supersecretvalue123"
    red = redact_secrets(text)
    check("key shapes redacted", "ghp_" not in red and "sk-ABC" not in red and "supersecretvalue123" not in red and "<REDACTED>" in red)
    with patch.dict("os.environ", {"MY_SERVICE_TOKEN": "liveenvvalue12345"}):
        red = redact_secrets("body with liveenvvalue12345 inside")
        check("env values redacted", "liveenvvalue12345" not in red)

    # ── 5. fetch pipeline with mocked HTTP ───────────────────────────
    fake_resp = SimpleNamespace(status_code=200, text=PAGE_HTML)
    p1, p2 = cfg_patches()
    with p1, p2, patch("rex.websearch._http_get", return_value=(200, PAGE_HTML)):
        out = web_fetch("https://example.com/page")
    check("fetch title present", "Kerja API — Panduan" in out)
    check("fetch strips scripts and tags", "alert(" not in out and "<p>" not in out)
    check("fetch redacts secrets", "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456" not in out)

    fake_404 = SimpleNamespace(status_code=404, text="")
    p1, p2 = cfg_patches()
    with p1, p2, patch("rex.websearch._http_get", return_value=(404, "")):
        check("non-200 reported", "HTTP 404" in web_fetch("https://example.com/gone"))

    p1, p2 = cfg_patches({"max_chars": 500})
    with p1, p2, patch("rex.websearch._http_get", return_value=(200, "x" * 5000)):
        out = web_fetch("https://example.com/big")
    check("fetch output capped", len(out) <= 550 and "DIPOTONG" in out)

    # ── 6. search parsing (mocked DDG HTML) ──────────────────────────
    out = _render_results(DDG_HTML, 8000)
    check("ddg uddg unwrapped", "https://docs.python.org/3/" in out)
    check("titles parsed", "Python docs" in out and "Example Guide" in out)
    check("snippet parsed", "Official Python docs site" in out)
    check("non-http links dropped", "ftp://nope.example" not in out)

    p1, p2 = cfg_patches()
    with p1, p2, patch("rex.websearch._ddg_search", return_value=DDG_HTML):
        out = web_search("python docs")
    check("search returns numbered results", out.startswith("1. Python docs") and "2. Example Guide" in out)

    p1, p2 = cfg_patches({"enabled": False})
    with p1, p2:
        check("search disabled by config", "nonaktif" in web_search("q"))
    p1, p2 = cfg_patches()
    with p1, p2, patch("rex.websearch.request_approval", return_value=False):
        check("search approval gate", "DITOLAK PENGGUNA" in web_search("q"))
    p1, p2 = cfg_patches()
    with p1, p2, patch("rex.websearch.request_approval", return_value=False):
        check("fetch approval gate", "DITOLAK PENGGUNA" in web_fetch("https://example.com"))

    # ── 7. registry wiring ───────────────────────────────────────────
    from rex.tools import TOOL_DEFINITIONS, TOOL_REGISTRY
    check("tools registered", "web_search" in TOOL_REGISTRY and "web_fetch" in TOOL_REGISTRY)
    defined = {item["name"] for item in TOOL_DEFINITIONS}
    check("schemas defined", {"web_search", "web_fetch"} <= defined)
    from rex.plugins import effective_tool_registry
    check("effective registry exposes web tools", "web_search" in effective_tool_registry() and "web_fetch" in effective_tool_registry())

    print("\nAll websearch checks PASS")


if __name__ == "__main__":
    main()
