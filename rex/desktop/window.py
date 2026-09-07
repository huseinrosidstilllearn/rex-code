"""
rex.desktop.window
===================
Open the Rex Desktop UI as a native OS window — no heavy framework.

Strategy: launch Edge/Chrome with ``--app=<url>`` (address-bar-less window
with its own taskbar icon) and fall back to the default browser when no
Chromium browser is found. Windows/macOS/Linux covered with stdlib only.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import List

from rex.logging_setup import log

_WINDOW_SIZE = "--window-size=1440,900"
_NO_FIRST_RUN = "--no-first-run"


def _exe_candidates() -> List[str]:
    """Chromium executables to try, best (Edge) first."""
    out: List[str] = []
    if sys.platform == "win32":
        out += [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
        for exe in ("msedge", "chrome"):
            found = shutil.which(exe)
            if found:
                out.append(found)
    elif sys.platform == "darwin":
        out += [
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    else:
        out += [
            "microsoft-edge", "microsoft-edge-stable",
            "google-chrome", "google-chrome-stable",
            "chromium", "chromium-browser",
        ]
        out = [shutil.which(exe) or exe for exe in out]
    # de-dup, keep order, keep only what exists
    seen: set = set()
    final: List[str] = []
    for exe in out:
        if exe and exe not in seen:
            seen.add(exe)
            if Path(exe).exists():
                final.append(exe)
    return final


def open_app_window(url: str) -> bool:
    """
    Try every Chromium browser in --app mode; fall back to the default
    browser. Returns True when an app-mode window opened.
    """
    for exe in _exe_candidates():
        try:
            subprocess.Popen(
                [exe, f"--app={url}", _WINDOW_SIZE, _NO_FIRST_RUN],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log.info("rex desktop window opened via %s", exe)
            return True
        except OSError:
            continue
    webbrowser.open(url)
    log.info("no chromium browser found — opened in default browser instead")
    return False


def open_browser_tab(url: str) -> None:
    """Plain browser tab (the --web entry)."""
    webbrowser.open(url)
    log.info("rex desktop opened in browser at %s", url)
