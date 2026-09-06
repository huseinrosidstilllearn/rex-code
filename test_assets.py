"""Self-check for brand assets (icons, installer wizard, Linux desktop). Run: python test_assets.py"""

import configparser
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
BRAND = ASSETS / "brand"

# Canonical build asset -> verbatim pack file (must stay byte-identical)
MIRRORS = {
    "icon.ico": "RexCode-Graphite.ico",
    "icon.icns": "RexCode-Graphite.icns",
    "installer/wizard.bmp": "InnoSetup-WizardImage.bmp",
    "installer/wizard-small.bmp": "InnoSetup-WizardSmallImage.bmp",
    "installer/banner.png": "RexCode-Installer-Banner.png",
}
for _size in (48, 64, 96, 128, 192, 256, 512):
    MIRRORS[f"linux/icons/rexcode-{_size}.png"] = f"RexCode-AppIcon-Graphite-{_size}.png"

ICO_SIZES = {16, 24, 32, 48, 64, 128, 256}
PACK_PNG_SIZES = (16, 20, 24, 32, 40, 48, 64, 72, 96, 128, 144, 152, 180, 192, 256, 384, 512, 1024)
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


def png_size(data: bytes):
    return struct.unpack(">II", data[16:24])


def main():
    # --- 1. canonical mirrors are byte-identical to the pack --------------
    for canonical, pack in MIRRORS.items():
        check(f"mirror {canonical} == brand/{pack}",
              (ASSETS / canonical).read_bytes() == (BRAND / pack).read_bytes())

    # --- 2. pack completeness (both color variants, every size) ------------
    for variant in ("Graphite", "Green"):
        for size in PACK_PNG_SIZES:
            p = BRAND / f"RexCode-AppIcon-{variant}-{size}.png"
            data = p.read_bytes() if p.is_file() else b""
            dims = png_size(data) if data[:8] == PNG_MAGIC else (0, 0)
            check(f"pack PNG {variant}-{size} square+valid", dims == (size, size))
        check(f"pack {variant}.ico present", (BRAND / f"RexCode-{variant}.ico").is_file())
        check(f"pack {variant}.icns present", (BRAND / f"RexCode-{variant}.icns").is_file())
        for size in (48, 64, 96, 128, 192, 256, 512):
            check(f"pack linux/{variant}-{size} present",
                  (BRAND / "linux" / f"RexCode-{variant}-{size}.png").is_file())
    check("pack linux/RexCode.desktop archived", (BRAND / "linux" / "RexCode.desktop").is_file())
    check("pack README archived", (BRAND / "README.txt").is_file())

    # --- 3. Windows icon: multi-size ICO (sharp at every Explorer zoom) ---
    ico = (ASSETS / "icon.ico").read_bytes()
    _res, typ, count = struct.unpack("<HHH", ico[:6])
    sizes = {ico[6 + 16 * i] or 256 for i in range(count)}
    check("icon.ico type=1", typ == 1)
    check("icon.ico contains 16..256", sizes == ICO_SIZES)

    # --- 4. Inno Setup wizard images (164x314 / 55x55, 24bpp) -------------
    for name, (w, h) in {"installer/wizard.bmp": (164, 314),
                         "installer/wizard-small.bmp": (55, 55)}.items():
        data = (ASSETS / name).read_bytes()
        dims = struct.unpack("<ii", data[18:26])
        bpp = struct.unpack("<H", data[28:30])[0]
        check(f"{name} {w}x{h} @24bpp", (dims, bpp) == ((w, h), 24))

    # --- 5. macOS icns ------------------------------------------------------
    check("icon.icns magic", (ASSETS / "icon.icns").read_bytes()[:4] == b"icns")

    # --- 6. Linux hicolor icons ---------------------------------------------
    for size in (48, 64, 96, 128, 192, 256, 512):
        data = (ASSETS / f"linux/icons/rexcode-{size}.png").read_bytes()
        ok = data[:8] == PNG_MAGIC and png_size(data) == (size, size)
        check(f"linux icon rexcode-{size} square+valid", ok)

    # --- 7. desktop entry template -----------------------------------------
    desktop = ASSETS / "rexcode.desktop"
    raw = desktop.read_bytes()
    check("rexcode.desktop LF-only", b"\r" not in raw)
    parser = configparser.ConfigParser()
    parser.optionxform = str
    parser.read_string(raw.decode("utf-8"))
    entry = parser["Desktop Entry"]
    for key, expected in {"Type": "Application", "Name": "Rex Code",
                          "Exec": "__REX_BIN__", "Icon": "rexcode",
                          "Terminal": "true"}.items():
        check(f"rexcode.desktop {key}={expected}", entry.get(key) == expected)

    # --- 8. Linux setup script ----------------------------------------------
    raw = (ASSETS / "linux" / "setup.sh").read_bytes()
    text = raw.decode("utf-8")
    check("setup.sh LF-only", b"\r" not in raw)
    check("setup.sh has --uninstall mode", "--uninstall" in text)
    check("setup.sh installs hicolor icons", "icons/rexcode-" in text)
    check("setup.sh renders Exec placeholder", "s|__REX_BIN__|" in text)

    # --- 9. build wiring ----------------------------------------------------
    iss = (ROOT / "installer" / "windows" / "rexcode.iss").read_text(encoding="utf-8")
    check("iss SetupIconFile -> assets/icon.ico",
          "SetupIconFile=..\\..\\assets\\icon.ico" in iss)
    check("iss wizard images wired",
          "WizardImageFile=..\\..\\assets\\installer\\wizard.bmp" in iss
          and "WizardSmallImageFile=..\\..\\assets\\installer\\wizard-small.bmp" in iss)
    spec = (ROOT / "installer" / "windows" / "rex.spec").read_text(encoding="utf-8")
    check("spec icon windows-only", 'sys.platform == "win32"' in spec and "icon=ICON" in spec)
    check("spec icon path is assets/icon.ico", '"assets" / "icon.ico"' in spec)
    ci = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    check("CI stages Linux desktop files into zip",
          "Stage Linux desktop integration files" in ci
          and "cp -r assets/linux/icons dist/RexCode/assets/linux/" in ci)
    gitattr = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    check("gitattributes keeps sh/desktop LF",
          "*.sh text eol=lf" in gitattr and "*.desktop text eol=lf" in gitattr)
    check("gitattributes marks binaries",
          "*.png binary" in gitattr and "*.ico binary" in gitattr)
    check("assets README exists", (ASSETS / "README.md").is_file())
    check("rex-here.cmd still shipped", (ASSETS / "rex-here.cmd").is_file())

    print("\nAll asset checks PASS")


if __name__ == "__main__":
    main()
