# Assets

Everything visual that the OS installers and builds consume lives here.

| Path | Used by |
| --- | --- |
| `icon.ico` | Windows — embedded in `rex.exe` (`rex.spec`), installer `SetupIconFile`, Explorer context-menu icon, `{app}\icon.ico` |
| `icon.icns` | macOS builds (`rex.spec`, darwin) |
| `installer/wizard.bmp` (164x314) + `installer/wizard-small.bmp` (55x55) | Inno Setup wizard branding (`rexcode.iss`) |
| `installer/banner.png` | Release/social banner |
| `linux/icons/rexcode-*.png` | hicolor app icons (staged into the Linux zip by `release.yml`) |
| `rexcode.desktop` + `linux/setup.sh` | Linux app-menu entry + install/uninstall script |
| `rex-here.cmd` | "Open Rex Code here" Explorer menu |
| `brand/` | Full professional asset pack (Graphite + Green variants) — the source of truth |

## Conventions

- `brand/` is the verbatim professional asset pack (Graphite + Green variants,
  incl. its `linux/` subfolder); the canonical files above are
  **byte-identical mirrors** (guarded by `test_assets.py`).
- The pack's stock `brand/linux/RexCode.desktop` is archival only — the shipped
  entry is `assets/rexcode.desktop` (Rex is a TUI: `Terminal=true`, exec `rex`).
- To change a build asset: update it in `brand/`, re-copy to the canonical
  path, then run `python test_assets.py`.
- Git keeps `*.sh` / `*.desktop` LF-only on every platform (`.gitattributes`)
  — the CI runners execute them on Linux.
