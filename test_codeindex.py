"""Self-check code index (/ask + import graph). Run: python test_codeindex.py"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rex.codeindex import (
    build_index,
    format_ask,
    format_import_graph,
    import_graph,
    query,
)


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


def main():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        (root / "rex").mkdir()
        (root / "rex" / "auth.py").write_text(
            "def check_auth(token):\n    return bool(token)\n\n"
            "class AuthService:\n    def refresh(self):\n        return 1\n",
            encoding="utf-8",
        )
        (root / "rex" / "core.py").write_text(
            "from rex.auth import check_auth\n\n"
            "def run_agent():\n    return check_auth('t')\n",
            encoding="utf-8",
        )
        (root / "app.js").write_text(
            "import { helper } from './util.js';\nexport function boot() { return 1; }\n",
            encoding="utf-8",
        )
        (root / "util.js").write_text("export function helper() { return 2; }\n", encoding="utf-8")
        (root / "notes.md").write_text("authentication uses tokens here\n", encoding="utf-8")
        skip = root / "__pycache__"
        skip.mkdir()
        (skip / "junk.py").write_text("def should_not_appear(): pass\n", encoding="utf-8")

        # ── 1. Build index ────────────────────────────────────────────────
        index = build_index(force=True, root=root)
        files = index["files"]
        check("py files indexed", "rex/auth.py" in files and "rex/core.py" in files)
        check("js files indexed", "app.js" in files)
        check("md indexed", "notes.md" in files)
        check("skip dirs excluded", not any("__pycache__" in f for f in files))

        # Symbols
        auth_symbols = {s["name"] for s in files["rex/auth.py"]["symbols"]}
        check("python symbols extracted", "check_auth" in auth_symbols and "AuthService" in auth_symbols)
        js_symbols = {s["name"] for s in files["app.js"]["symbols"]}
        check("js symbols extracted", "boot" in js_symbols)

        # ── 2. Signature caching ─────────────────────────────────────────
        index2 = build_index(root=root)  # no force; signature unchanged
        check("cache reused", index2["files"] == files)

        # Mutation invalidates
        (root / "rex" / "auth.py").write_text("def check_auth(token):\n    return 1\n\ndef added_fn(): pass\n", encoding="utf-8")
        index3 = build_index(root=root)
        names3 = {s["name"] for s in index3["files"]["rex/auth.py"]["symbols"]}
        check("mutation refreshes index", "added_fn" in names3)

        # ── 3. Query: symbol, file name, content ─────────────────────────
        hits = query(index3, "check_auth")
        check("symbol hit first", hits and hits[0]["kind"] == "def" and hits[0]["file"] == "rex/auth.py")
        hits = query(index3, "auth.py")
        check("file name hit", any(h["kind"] == "file" and h["file"] == "rex/auth.py" for h in hits))
        hits = query(index3, "authentication", root=root)
        check("content hit in md", any(h["kind"] == "content" and h["file"] == "notes.md" for h in hits))
        check("no hit -> empty", query(index3, "zzz_nothing_zzz") == [])

        # ── 4. Import graph (python + js local resolution) ───────────────
        graph = import_graph(index3)
        check("py import resolved", graph.get("rex/core.py") == ["rex/auth"])
        check("js import resolved", graph.get("app.js") == ["util.js"])

        text = format_import_graph(index3)
        check("graph renders", "rex/core.py -> rex/auth" in text)

        # ── 5. format_ask ────────────────────────────────────────────────
        report = format_ask(index3, "check_auth", root=root)
        check("ask renders hit", "rex/auth.py" in report and "def check_auth" in report)
        check("ask empty message", "Tidak ditemukan" in format_ask(index3, "zzz_nothing_zzz", root=root))

        # ── 6. Index persists to .rex/index.json ─────────────────────────
        persisted = root / ".rex" / "index.json"
        check("index file written", persisted.is_file())

        # ── 7. @file:symbol spans (locate_symbol_span) ───────────────────
        from rex.codeindex import complete_reference, locate_symbol_span

        py_source = (
            "import os\n\n"
            "def check_auth(token):\n"
            "    return bool(token)\n"
            "\n"
            "class AuthService:\n"
            "    attr = 1\n"
            "\n"
            "    def refresh(self):\n"
            "        return 2\n"
            "\n"
            "def tail_fn():\n"
            "    pass\n"
        )
        span = locate_symbol_span(py_source, "check_auth", python=True)
        lines = py_source.splitlines()
        check("def span exact", span == (3, 4))
        check("def span content", lines[span[0] - 1].startswith("def check_auth") and lines[span[1] - 1] == "    return bool(token)")

        span = locate_symbol_span(py_source, "authservice", python=True)  # case-insensitive
        class_text = "\n".join(lines[span[0] - 1:span[1]]) if span else ""
        check("class span includes methods", "class AuthService" in class_text and "def refresh" in class_text and "return 2" in class_text)
        check("class span ends before tail_fn", "tail_fn" not in class_text)

        check("partial name match", locate_symbol_span(py_source, "auth", python=True) is not None)
        check("unknown symbol -> None", locate_symbol_span(py_source, "zzz_none", python=True) is None)
        check("empty symbol -> None", locate_symbol_span(py_source, "", python=True) is None)

        js_source = "function boot() {\n  return 1;\n}\n\nfunction helper() {\n  return 2;\n}\n"
        span = locate_symbol_span(js_source, "boot", python=False)
        check("generic span ends at next symbol", span == (1, 3))
        check("generic last symbol to EOF", locate_symbol_span(js_source, "helper", python=False) == (5, 7))

        # ── 8. complete_reference (@ autocomplete) ───────────────────────
        index = build_index(force=True, root=root)
        check("complete by path prefix", "rex/auth.py" in complete_reference(index, "rex/auth"))
        check("complete by substring", "rex/core.py" in complete_reference(index, "core"))
        check("complete by filename", "app.js" in complete_reference(index, "app."))
        check("complete respects limit", len(complete_reference(index, "", limit=3)) == 0)  # empty token -> none
        check("no match -> empty", complete_reference(index, "zzz_none") == [])

        sym = complete_reference(index, "rex/auth.py:auth")
        check("complete file:symbol", "rex/auth.py:check_auth" in sym)
        check("complete symbol exact", "rex/auth.py:added_fn" in complete_reference(index, "rex/auth.py:added"))

        # ── 9. vision integration: @file:symbol inlines the span ────────
        from rex.vision import extract_references
        prompt, attachments, notes = extract_references(
            "jelaskan @rex/auth.py:check_auth sekilas", base_dir=root
        )
        joined = "\n".join(notes)
        check("symbol excerpt inlined", "Isi @rex/auth.py:check_auth (cuplikan):" in joined)
        check("excerpt scoped to span", "def check_auth" in joined and "added_fn" not in joined)
        prompt2, _, notes2 = extract_references("cari @rex/auth.py:missing_sym", base_dir=root)
        check("missing symbol noted", any("tidak ditemukan" in n for n in notes2))
        prompt3, _, notes3 = extract_references("baca @rex/auth.py", base_dir=root)
        check("plain @file still full inline", any("Isi @rex/auth.py:" in n and "return 1" in n for n in notes3))

    print("\nCodeindex checks ALL PASS")


if __name__ == "__main__":
    main()
