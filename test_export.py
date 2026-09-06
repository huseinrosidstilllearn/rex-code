"""Self-check session export (rex/export.py). Run: python test_export.py"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rex.export import build_html, build_markdown, export_session, export_path
from rex.sessions import SessionStore


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


class FakeUsage:
    def __init__(self, prompt, completion, total=None):
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = total


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        store = SessionStore(tmp_dir / "sessions")
        sid = store.create("gemini", "gemini-flash-latest")["id"]
        store.append(sid, {"role": "user", "content": "Buatkan fungsi <cek> kuotaku"})
        store.append(sid, {"role": "assistant", "content": "Baik, ini **implementasinya**:\n```py\nx=1\n```"})
        store.append(sid, {"role": "tool", "name": "run_command", "content": "exit 0"})
        with patch("rex.core.session_store", store), patch("rex.sessions.session_store", store):
            pass  # add_usage patches not needed; call directly
        store.add_usage(sid, FakeUsage(1000, 500))

        data = store.load(sid)
        costs = {"gemini-flash-latest": {"input": 0.10, "output": 0.40}}

        # ── 1. Markdown build ────────────────────────────────────────────
        md = build_markdown(data, costs)
        check("md has title header", "# " in md.splitlines()[0])
        check("md meta line", "gemini-flash-latest" in md and data["id"] in md)
        check("md user turn", "## You" in md and "Buatkan fungsi <cek> kuotaku" in md)
        check("md assistant turn", "## Rex" in md and "**implementasinya**" in md)
        check("md tool turn fenced", "## Tool" in md and "[tool run_command] exit 0" in md)
        check("md usage footer", "Token: 1,500" in md and "$0.0003" in md)

        # ── 2. HTML build ────────────────────────────────────────────────
        page = build_html(data, costs)
        check("html is standalone", page.startswith("<!DOCTYPE html>") and "<style>" in page)
        check("html escapes content", "&lt;cek&gt;" in page and "<script>" not in page)
        check("html tool block", "tool" in page and "exit 0" in page)
        check("html usage footer", "Token: 1,500" in page)

        # ── 3. export_session md ─────────────────────────────────────────
        out_dir = tmp_dir / "out"
        with patch("rex.sessions.session_store", store), \
             patch("rex.export.load_config", return_value={"model_costs": costs}), \
             patch("rex.export.normalize_config", side_effect=lambda c: c):
            result = export_session(sid, fmt="md", out_dir=out_dir)
        check("md export message", result.startswith("Diekspor ke "))
        path = Path(result[len("Diekspor ke "):])
        check("md file exists", path.is_file() and path.suffix == ".md")
        check("md filename pattern", path.name.startswith(f"rex-{sid[:8]}-"))
        content = path.read_text(encoding="utf-8")
        check("md file content", "Buatkan fungsi" in content and "Token: 1,500" in content)

        # ── 4. export_session html ───────────────────────────────────────
        with patch("rex.sessions.session_store", store), \
             patch("rex.export.load_config", return_value={"model_costs": costs}), \
             patch("rex.export.normalize_config", side_effect=lambda c: c):
            result = export_session(sid, fmt="html", out_dir=out_dir)
        check("html export message", result.startswith("Diekspor ke ") and result.endswith(".html"))
        page = Path(result[len("Diekspor ke "):]).read_text(encoding="utf-8")
        check("html file content", page.startswith("<!DOCTYPE html>") and "Buatkan fungsi" in page)

        # ── 5. error paths ───────────────────────────────────────────────
        check("bad format rejected", "tidak dikenal" in export_session(sid, fmt="pdf", out_dir=out_dir))
        with patch("rex.sessions.session_store", store), \
             patch("rex.export.load_config", return_value={}), \
             patch("rex.export.normalize_config", side_effect=lambda c: c):
            check("format with dot accepted", "Diekspor" in export_session(sid, fmt=".md", out_dir=out_dir))
        check("unknown session rejected", "tidak bisa dimuat" in export_session("ffffffffffffffffffffffffffffffff", out_dir=out_dir))
        check("invalid session id rejected", "tidak bisa dimuat" in export_session("nope"))

        # Redacted secrets stay redacted in exports
        sid2 = store.create("gemini", "m1")["id"]
        store.append(sid2, {"role": "assistant", "content": "key: [REDACTED]"})
        with patch("rex.sessions.session_store", store), \
             patch("rex.export.load_config", return_value={}), \
             patch("rex.export.normalize_config", side_effect=lambda c: c):
            result = export_session(sid2, out_dir=out_dir)
        content = Path(result[len("Diekspor ke "):]).read_text(encoding="utf-8")
        check("export keeps redaction", "[REDACTED]" in content)

        check("deterministic path shape", export_path(sid, "md", out_dir=out_dir).parent == out_dir)

    print("\nAll export checks PASS")


if __name__ == "__main__":
    main()
