"""Self-check for unified diff parse/apply (rex.diffs + apply_patch tool). Run: python test_diffs.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rex import diffs
from rex.tools import apply_patch


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


SAMPLE = """--- a/app.py
+++ b/app.py
@@ -1,4 +1,4 @@
 line1
-line2
+LINE2
 line3
 line4
"""


def main():
    # ── parse_diff basics ──────────────────────────────────────────────
    entries = diffs.parse_diff(SAMPLE)
    check("one file parsed", len(entries) == 1)
    entry = entries[0]
    check("old path", entry["old_path"] == "app.py")
    check("new path", entry["new_path"] == "app.py")
    check("one hunk", len(entry["hunks"]) == 1)
    hunk = entry["hunks"][0]
    check("hunk start", hunk["old_start"] == 1)
    tags = [t for t, _ in hunk["lines"]]
    check("hunk tags", tags == [" ", "-", "+", " ", " "])

    # git-style metadata is tolerated
    GIT_STYLE = """diff --git a/x.py b/x.py
index 1234567..89abcde 100644
--- a/x.py
+++ b/x.py
@@ -1 +1 @@
-a
+b
"""
    git_entries = diffs.parse_diff(GIT_STYLE)
    check("git metadata ignored", git_entries[0]["old_path"] == "x.py" and len(git_entries[0]["hunks"]) == 1)

    # /dev/null: create + delete
    CREATE = """--- /dev/null
+++ b/new_file.py
@@ -0,0 +1,2 @@
+alpha
+beta
"""
    ce = diffs.parse_diff(CREATE)
    check("create detected", diffs.created_file(ce[0]) and not diffs.deleted_file(ce[0]))
    check("new file content", diffs.build_new_file(ce[0]["hunks"]) == "alpha\nbeta\n")

    DELETE = """--- a/old.txt
+++ /dev/null
@@ -1,1 +0,0 @@
-gone
"""
    de = diffs.parse_diff(DELETE)
    check("delete detected", diffs.deleted_file(de[0]) and not diffs.created_file(de[0]))

    # malformed patches raise
    for bad, why in [
        ("", "empty"),
        ("+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n", "plus-plus without minus-minus"),
    ]:
        try:
            diffs.parse_diff(bad)
            check(f"malformed rejected ({why})", False)
        except diffs.DiffError:
            check(f"malformed rejected ({why})", True)

    # ── apply_to_text ─────────────────────────────────────────────────
    text = "line1\nline2\nline3\nline4\n"
    patched = diffs.apply_to_text(text, entries[0]["hunks"])
    check("simple apply", patched == "line1\nLINE2\nline3\nline4\n")

    # fuzzy: hunk states the wrong line number but context is unique
    FUZZY = """--- a/f.py
+++ b/f.py
@@ -50,1 +50,1 @@
-x
+root
"""
    try:
        diffs.apply_to_text("a\nroot\nb\n", diffs.parse_diff(FUZZY)[0]["hunks"])
        check("fuzzy match on unique context", False)
    except diffs.DiffError:
        # '-x' is not present at all -> must fail
        check("fuzzy match on unique context", True)

    MATCH = """--- a/f.py
+++ b/f.py
@@ -40,1 +40,1 @@
-b
+B!
"""
    result = diffs.apply_to_text("a\nb\nc\n", diffs.parse_diff(MATCH)[0]["hunks"])
    check("drifted line number still matches", result == "a\nB!\nc\n")

    # multiple hunks in one file
    MULTI = """--- a/m.py
+++ b/m.py
@@ -1,2 +1,2 @@
-one
+ONE
 two
@@ -5,2 +5,2 @@
 five
-six
+SIX
"""
    mtext = "one\ntwo\nthree\nfour\nfive\nsix\n"
    mres = diffs.apply_to_text(mtext, diffs.parse_diff(MULTI)[0]["hunks"])
    check("multi hunk apply", mres == "ONE\ntwo\nthree\nfour\nfive\nSIX\n")

    # ── apply_patch tool (mode gate + atomicity) ──────────────────────
    from rex.config import set_active_mode
    import tempfile

    set_active_mode("plan")
    blocked = apply_patch(SAMPLE)
    check("plan mode blocks apply_patch", "TIDAK DIIZINKAN" in blocked)

    set_active_mode("build")
    with tempfile.TemporaryDirectory() as tmp:
        # Point the sandbox at the temp dir for this block
        import rex.tools as tools
        original_target = tools._target
        ws = Path(tmp)
        (ws / "app.py").write_text("line1\nline2\nline3\nline4\n", encoding="utf-8")

        def temp_target(path):
            normalized = str(path).replace("\\\\", "/")
            resolved = (ws / normalized).resolve()
            return resolved if str(resolved).startswith(str(ws.resolve())) else None

        tools._target = temp_target
        try:
            ok = apply_patch(SAMPLE)
            check("tool applies patch", "Patch diterapkan" in ok)
            check("file content patched", (ws / "app.py").read_text(encoding="utf-8") == "line1\nLINE2\nline3\nline4\n")

            # no-half-write: second file's bad hunk must leave the first untouched
            (ws / "app.py").write_text("line1\nline2\nline3\nline4\n", encoding="utf-8")
            BAD = SAMPLE + """--- a/missing.py
+++ b/missing.py
@@ -1,1 +1,1 @@
-nope
+yes
"""
            fail = apply_patch(BAD)
            check("bad hunk aborts whole patch", "tidak ada file yang diubah" in fail or "Error" in fail)
            check("first file untouched after abort", (ws / "app.py").read_text(encoding="utf-8") == "line1\nline2\nline3\nline4\n")

            # create + delete via patch
            CREATE_FULL = """--- /dev/null
+++ b/made.py
@@ -0,0 +1,1 @@
+hello
"""
            ok2 = apply_patch(CREATE_FULL)
            check("patch creates file", (ws / "made.py").exists() and "hello" in (ws / "made.py").read_text(encoding="utf-8"))

            DELETE_FULL = """--- a/made.py
+++ /dev/null
@@ -1,1 +0,0 @@
-hello
"""
            ok3 = apply_patch(DELETE_FULL)
            check("patch deletes file", not (ws / "made.py").exists())

            # sensitive path blocked
            SENS = """--- /dev/null
+++ b/.env
@@ -0,0 +1,1 @@
+x
"""
            denied = apply_patch(SENS)
            check("sensitive path blocked", "DIBLOKIR" in denied)
        finally:
            tools._target = original_target

    set_active_mode("plan")  # leave the config as we found it


if __name__ == "__main__":
    main()

