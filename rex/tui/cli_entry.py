"""
rex.tui.cli_entry
=================
Console entry point for Rex Code (source CLI and PyInstaller-frozen exe).

Supports:
    rex            -> launch the Textual TUI
    rex --version  -> print version and exit (used to smoke-test frozen builds)
"""

import sys
from pathlib import Path

# Allow direct invocation: `python rex/tui/cli_entry.py --version`
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import rex


def main() -> None:
    args = sys.argv[1:]
    if any(a in ("--version", "-V") for a in args):
        print(f"Rex Code v{rex.__version__}")
        return
    from rex.tui.app import main as tui_main

    tui_main()


if __name__ == "__main__":
    main()
