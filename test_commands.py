"""Self-check for custom slash commands (rex.commands). Run: python test_commands.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rex import commands


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


def main():
    # ── Front-matter parsing ──────────────────────────────────────────
    meta, body = commands._parse_front_matter(
        "---\ndescription: Uji coba\n---\nIsi prompt"
    )
    check("front-matter description parsed", meta.get("description") == "Uji coba")
    check("front-matter stripped from body", body.strip() == "Isi prompt")

    meta2, body2 = commands._parse_front_matter("Langsung isi tanpa front-matter")
    check("no front-matter -> empty meta", meta2 == {})
    check("no front-matter -> body intact", body2 == "Langsung isi tanpa front-matter")

    # ── Name normalization & validation ────────────────────────────────
    check("normalize name lowercases", commands._normalize_name("Review.md") == "review")
    check("normalize name replaces invalid chars", commands._normalize_name("My Cmd!.md") == "my-cmd-")
    check("valid name accepted", commands._valid_name("review"))
    check("invalid name rejected", not commands._valid_name(""))
    check("overlong name rejected", not commands._valid_name("a" * (commands.MAX_NAME_LEN + 1)))

    # ── parse_input ───────────────────────────────────────────────────
    cmd, args = commands.parse_input("/review src/app.py")
    check("parse_input splits command", cmd == "/review")
    check("parse_input splits arguments", args == "src/app.py")
    cmd2, args2 = commands.parse_input("/check")
    check("parse_input no arguments", (cmd2, args2) == ("/check", ""))
    cmd3, args3 = commands.parse_input("pertanyaan biasa")
    check("parse_input non-command passthrough", (cmd3, args3) == ("", "pertanyaan biasa"))

    # ── expand_prompt ($ARGUMENTS) ─────────────────────────────────────
    sample = {"name": "t", "description": "", "prompt": "Tinjau $ARGUMENTS sekarang"}
    check(
        "$ARGUMENTS substituted",
        commands.expand_prompt(sample, "file.py") == "Tinjau file.py sekarang",
    )
    check(
        "$ARGUMENTS empty ok",
        commands.expand_prompt(sample, "") == "Tinjau  sekarang",
    )
    plain = {"name": "t", "description": "", "prompt": "Lakukan pemeriksaan"}
    check(
        "no placeholder appends args",
        commands.expand_prompt(plain, "app.py") == "Lakukan pemeriksaan\napp.py",
    )
    check(
        "no placeholder no args unchanged",
        commands.expand_prompt(plain, "") == "Lakukan pemeriksaan",
    )

    # ── load_commands against a temp workspace ────────────────────────
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cdir = root / ".rex" / "commands"
        cdir.mkdir(parents=True)

        # 1) normal command with front-matter
        (cdir / "review.md").write_text(
            "---\ndescription: Ulas kode\n---\nUlas kode berikut: $ARGUMENTS",
            encoding="utf-8",
        )
        # 2) command without front-matter
        (cdir / "deploy.md").write_text("Deploy aplikasi", encoding="utf-8")
        # 3) collision with built-in -> must be skipped
        (cdir / "plan.md").write_text("prompt jahat", encoding="utf-8")
        # 4) empty file -> must be skipped
        (cdir / "empty.md").write_text("", encoding="utf-8")
        # 5) non-md extension -> must be ignored
        (cdir / "ignored.txt").write_text("x", encoding="utf-8")

        loaded = commands.load_commands(root)
        check("loads valid commands", set(loaded) == {"/review", "/deploy"})
        check("front-matter description kept", loaded["/review"]["description"] == "Ulas kode")
        check("prompt body kept", "Ulas kode berikut" in loaded["/review"]["prompt"])
        check("built-in collision skipped", "/plan" not in loaded)
        check("empty file skipped", "/empty" not in loaded)
        check("txt ignored", "/ignored" not in loaded)

        check("empty dir -> empty dict", commands.load_commands(Path(tmp) / "nothing") == {})

    # ── format_help ────────────────────────────────────────────────────
    lines = commands.format_help({"/review": {"description": "Ulas kode"}})
    check("help lists custom command", any("/review" in l for l in lines))
    empty_lines = commands.format_help({})
    check("help without commands still renders", len(empty_lines) == 1)

    # ── BUILTIN_COMMANDS guard ────────────────────────────────────────
    check("built-ins reserved", "/plan" in commands.BUILTIN_COMMANDS and "/help" in commands.BUILTIN_COMMANDS)


if __name__ == "__main__":
    main()
