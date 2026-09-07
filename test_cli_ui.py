"""Self-check for the prompt_toolkit CLI UI layer (Fase D).
Covers: decide_frontend pure dispatch, SLASH_COMMANDS integrity,
completer/history/session wiring, ANSI prompt rendering, graceful
fallback when prompt_toolkit is missing. Run: python test_cli_ui.py"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cli  # noqa: E402


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


class _Args:
    def __init__(self, **kw):
        self.serve_webhook = False
        self.prompt = None
        self.web = False
        self.tui = False
        self.cli = False
        for k, v in kw.items():
            setattr(self, k, v)


def main():
    # ── decide_frontend: pure dispatch ────────────────────────
    check("default -> desktop", cli.decide_frontend(_Args()) == "desktop")
    check("--tui -> tui", cli.decide_frontend(_Args(tui=True)) == "tui")
    check("--cli -> tui", cli.decide_frontend(_Args(cli=True)) == "tui")
    check("--web -> web", cli.decide_frontend(_Args(web=True)) == "web")
    check("-p x -> headless", cli.decide_frontend(_Args(prompt="x")) == "headless")
    check("webhook wins over prompt", cli.decide_frontend(_Args(serve_webhook=True, prompt="x")) == "webhook")
    check("prompt wins over web", cli.decide_frontend(_Args(prompt="x", web=True)) == "headless")

    # ── SLASH_COMMANDS integrity ───────────────────────────────
    check("commands nonempty", len(cli.SLASH_COMMANDS) >= 25)
    check("all start with /", all(c.startswith("/") for c in cli.SLASH_COMMANDS))
    check("all unique", len(set(cli.SLASH_COMMANDS)) == len(cli.SLASH_COMMANDS))
    check("no mojibake in commands", all(ord(ch) < 128 for c in cli.SLASH_COMMANDS for ch in c))

    # ── completer + history wiring ─────────────────────────────
    comp = cli._repl_completer()
    check("completer is WordCompleter", type(comp).__name__ == "WordCompleter")
    words = set(getattr(comp, "words", []))
    check("completer words == SLASH_COMMANDS", words == set(cli.SLASH_COMMANDS))

    hist = cli._repl_history()
    check("history is FileHistory", type(hist).__name__ == "FileHistory")
    hist_path = str(getattr(hist, "filename", "")).replace("\\", "/")
    check("history file is cli_history", hist_path.endswith("/cli_history"))

    # ── session behavior (console-dependent, deterministic per env) ──
    session = cli._prompt_session()
    if sys.stdout.isatty():
        check("tty: session is PromptSession", session is not None and type(session).__name__ == "PromptSession")
        check("tty: session has completer", session is not None and getattr(session, "completer", None) is not None)
    else:
        # Piped/redirected stdout: prompt_toolkit has no win32 console buffer,
        # so _prompt_session must degrade to None (plain-input fallback).
        check("piped: session degrades to None", session is None)

    # ── ANSI prompt rendering (rich -> prompt_toolkit) ─────────
    from rich.console import Console
    from rich.text import Text
    ansi_console = Console(force_terminal=True)
    t = Text.from_markup("\n[bold green][Rex Code | BUILD | m1][/bold green] > ")
    with ansi_console.capture() as cap:
        ansi_console.print(t, end="")
    raw = cap.get()
    check("ansi prompt contains color", "\x1b[" in raw)
    check("ansi prompt contains label", "Rex Code" in raw)

    # ── fallback: pip uninstall style, via subprocess sandbox ──
    probe = (
        "import sys\n"
        "class _Blocker:\n"
        "    def find_module(self, name, path=None):\n"
        "        return None\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name == 'prompt_toolkit' or name.startswith('prompt_toolkit.'):\n"
        "            raise ImportError('blocked')\n"
        "        return None\n"
        "sys.meta_path.insert(0, _Blocker())\n"
        "import sys as _s\n"
        "_s.stdout.reconfigure(encoding='utf-8')\n"
        "import cli\n"
        "try:\n"
        "    cli._prompt_session()\n"
        "    print('SESSION_BUILT')\n"
        "except ImportError:\n"
        "    print('FALLBACK_OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True, text=True, encoding="utf-8",
        cwd=str(Path(__file__).resolve().parent),
    )
    out = (result.stdout or "") + (result.stderr or "")
    check("fallback probe rc==0", result.returncode == 0)
    check("graceful ImportError fallback", "FALLBACK_OK" in out)

    # ── cli.py source guards ───────────────────────────────────
    src = Path("cli.py").read_text(encoding="utf-8")
    check("main uses decide_frontend", "frontend = decide_frontend(args)" in src)
    check("repl uses pt_session", "pt_session.prompt(" in src)
    check("plain-input fallback kept", "console.input(prompt_text)" in src)
    check("stdout forced utf-8", "reconfigure(encoding=\"utf-8\")" in src)
    check("no mojibake chars", all(ch not in src for ch in ("\u00e2", "\u00c3", "\u00c2")))

    print("\nAll CLI-UI checks PASS")


if __name__ == "__main__":
    main()
