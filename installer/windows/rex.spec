# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec — Rex Code (Windows onedir build)
#
# Build from the repo root:
#     .venv\Scripts\pyinstaller.exe installer\windows\rex.spec --noconfirm
#
# Output:
#     dist/RexCode/rex.exe   (onedir bundle — fast TUI startup, no temp extraction)
#
# All paths resolve from SPECPATH (= installer/windows), so the spec works
# regardless of the working directory. No cwd hacks.

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

SPEC_DIR = Path(SPECPATH).resolve()          # installer/windows
PROJECT_ROOT = SPEC_DIR.parent.parent        # repo root

hiddenimports = [
    # LLM providers
    "google.genai",
    "google.genai.types",
    "openai",
    # TUI
    "textual",
    "textual.app",
    "textual.widgets",
    "textual.containers",
    "textual.reactive",
    "textual.binding",
    "textual.message",
    "textual.events",
    "textual.css",
    "textual.driver",
    "textual.worker",
    # Config / validation
    "pydantic",
    "pydantic_core",
    "dotenv",
    # Timezones (Windows has no system tz database)
    "tzdata",
    "zoneinfo",
]

datas = [
    # Default config, bundled where rex.config looks on first frozen run:
    # sys._MEIPASS / rex / config.json
    (str(PROJECT_ROOT / "config.json"), "rex"),
]

env_example = PROJECT_ROOT / ".env.example"
if env_example.exists():
    datas.append((str(env_example), "."))

# Textual ships tree-sitter highlighters + CSS the import scanner cannot see.
datas += collect_data_files("textual")
# tzdata ships the whole IANA database as data files.
datas += collect_data_files("tzdata")

# Only exclude heavy, genuinely-unused packages. Do NOT exclude stdlib
# modules like email/http — openai and google-genai depend on them.
excludes = [
    "tkinter",
    "pytest",
    "matplotlib",
    "numpy",
    "scipy",
    "pandas",
    "PIL",
    "cv2",
    "IPython",
    "notebook",
    "jupyter",
]

a = Analysis(
    [str(PROJECT_ROOT / "rex" / "tui" / "cli_entry.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="rex",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT_ROOT / "assets" / "icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="RexCode",
)
