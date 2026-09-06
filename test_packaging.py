"""Self-check for distribution manifests (winget + scoop). Run: python test_packaging.py"""

import importlib.util
import json
import re
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rex

ROOT = Path(__file__).resolve().parent
GEN = ROOT / "packaging" / "generate_manifests.py"
WINGET_DIR = ROOT / "packaging" / "winget"
INSTALLER_YAML = WINGET_DIR / "RexCodeTeam.RexCode.installer.yaml"
LOCALE_YAML = WINGET_DIR / "RexCodeTeam.RexCode.locale.en-US.yaml"
VERSION_YAML = WINGET_DIR / "RexCodeTeam.RexCode.yaml"
SCOOP_JSON = ROOT / "packaging" / "scoop" / "rexcode.json"
ISS = ROOT / "installer" / "windows" / "rexcode.iss"
ASSET_URL = "https://github.com/huseinrosidstilllearn/rex-code/releases/download"


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


def load_generator():
    """Import packaging/generate_manifests.py by path — avoids shadowing
    the pip 'packaging' library used by PyInstaller."""
    spec = importlib.util.spec_from_file_location("rex_packaging_gen", GEN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _version_tuple(v: str):
    """'v1.2.3' -> (1, 2, 3) — enough to prove a manifest is not newer
    than the code (no rex.updates import: that would pull httpx, which
    the manifest CI job deliberately does not install)."""
    digits = v.strip().lower().lstrip("v").split("-", 1)[0]
    return tuple(int(p) if p.isdigit() else 0 for p in digits.split("."))


def main():
    gen = load_generator()
    # The committed manifests pin the LAST RELEASED version — they are
    # synced post-release (see packaging/README.md), so they may lag
    # rex.__version__ mid-cycle. All consistency checks use the manifests'
    # own version; the only version rule is: never AHEAD of the code.
    scoop_doc = json.loads(SCOOP_JSON.read_text(encoding="utf-8"))
    version = scoop_doc["version"]
    expected_url = f"{ASSET_URL}/v{version}/RexCode-Setup-v{version}-x64.exe"

    # ── 1. Generator inputs (single sources of truth) ───────────────
    check("generator file exists", GEN.is_file())
    check("read_version matches rex.__version__", gen.read_version() == rex.__version__)
    check("read_version override works", gen.read_version("9.9.9") == "9.9.9")
    check("manifest version never ahead of code", _version_tuple(version) <= _version_tuple(rex.__version__))
    app_id = gen.read_app_id()
    iss_src = ISS.read_text(encoding="utf-8")
    check("AppId read from rexcode.iss", app_id in iss_src and re.fullmatch(r"[0-9A-Fa-f-]{36}", app_id))
    check("sha256 validator accepts + lowercases", gen._validate_sha256("A" * 64) == "a" * 64)
    try:
        gen._validate_sha256("nope")
        check("invalid sha256 rejected", False)
    except SystemExit:
        check("invalid sha256 rejected", True)

    # ── 2. Committed winget manifests ───────────────────────────────
    installer = INSTALLER_YAML.read_text(encoding="utf-8")
    locale = LOCALE_YAML.read_text(encoding="utf-8")
    version_yaml = VERSION_YAML.read_text(encoding="utf-8")
    sha_m = re.search(r"^\s*InstallerSha256: ([0-9A-F]{64})\s*$", installer, re.M)
    date_m = re.search(r"^ReleaseDate: (\d{4}-\d{2}-\d{2})$", installer, re.M)
    check("installer yaml exists", INSTALLER_YAML.is_file())
    check("winget version == app version", f"PackageVersion: {version}" in installer)
    check("PackageIdentifier consistent across all 3 files",
          all("RexCodeTeam.RexCode" in t for t in (installer, locale, version_yaml)))
    check("InstallerType inno", "InstallerType: inno" in installer)
    check("InstallerUrl follows release asset pattern", f"InstallerUrl: {expected_url}" in installer)
    check("InstallerSha256 is uppercase 64-hex", sha_m is not None)
    check("ReleaseDate is YYYY-MM-DD", date_m is not None)
    check("ProductCode derives from Inno AppId", f"ProductCode: {{{app_id}}}_is1" in installer)
    check("silent switch verysilent + norestart", "Silent: /SP- /VERYSILENT /SUPPRESSMSGBOXES /NORESTART" in installer)
    check("custom switch opts into addtopath task", "Custom: /TASKS=addtopath,keepdata" in installer)
    check("scope machine + elevatesSelf", "Scope: machine" in installer and "ElevationRequirement: elevatesSelf" in installer)
    check("commands expose rex", "Commands:\n- rex" in installer)
    check("locale publisher/license/moniker", "Publisher: Rex Code Team" in locale
          and "License: MIT" in locale and "Moniker: rexcode" in locale)
    check("locale + version manifest types", "ManifestType: defaultLocale" in locale
          and "ManifestType: version" in version_yaml and "DefaultLocale: en-US" in version_yaml)

    # ── 3. Committed scoop manifest ────────────────────────────────
    scoop = json.loads(SCOOP_JSON.read_text(encoding="utf-8"))
    check("scoop version == app version", scoop["version"] == version)
    check("scoop innosetup true (no installer execution)", scoop.get("innosetup") is True)
    check("scoop url == release asset", scoop["architecture"]["64bit"]["url"] == expected_url)
    check("scoop hash matches winget hash", scoop["architecture"]["64bit"]["hash"] == sha_m.group(1).lower())
    check("scoop bin shim rex.exe -> rex", scoop["bin"] == [["rex.exe", "rex"]])
    check("scoop checkver github", scoop["checkver"] == "github")
    au = scoop["autoupdate"]
    check("scoop autoupdate url templated", "$version" in au["architecture"]["64bit"]["url"])
    check("scoop autoupdate hash reads SHA256SUMS.txt",
          au["hash"]["url"].endswith("/SHA256SUMS.txt") and "$sha256" in au["hash"]["regex"] and "$basename" in au["hash"]["regex"])

    # ── 4. Committed manifests == generator render (byte-identical)
    sha, date = sha_m.group(1).lower(), date_m.group(1)
    check("installer yaml byte-identical to render",
          gen.render_winget_installer(version, sha, app_id, date) == installer)
    check("locale yaml byte-identical to render", gen.render_winget_locale(version) == locale)
    check("version yaml byte-identical to render", gen.render_winget_version(version) == version_yaml)
    check("scoop json byte-identical to render",
          gen.render_scoop(version, sha) == SCOOP_JSON.read_text(encoding="utf-8"))

    # ── 5. CLI behaviour ────────────────────────────────────────────
    buf = StringIO()
    with redirect_stdout(buf):
        code = gen.main(["--sha256", "b" * 64, "--print", "--version", "1.2.3"])
    check("main --print renders without writing",
          code == 0 and "RexCodeTeam.RexCode" in buf.getvalue() and "1.2.3" in buf.getvalue())
    try:
        gen.main([])
        check("main without hash source exits 2", False)
    except SystemExit as exc:
        check("main without hash source exits 2", exc.code == 2)

    print("\nPackaging manifest checks PASS")


if __name__ == "__main__":
    main()
