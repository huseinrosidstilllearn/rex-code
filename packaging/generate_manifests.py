#!/usr/bin/env python3
"""
Generate distribution manifests (winget + scoop) for Rex Code releases.

Single source of truth for everything version/hash dependent:
- winget installer/locale/version YAML  -> packaging/winget/
- scoop manifest                        -> packaging/scoop/rexcode.json

Inputs are read from the repo itself, never hardcoded here:
- version   : rex/__init__.py  __version__
- AppId GUID: installer/windows/rexcode.iss  AppId
- SHA256    : --sha256 <hex> or --fetch (GitHub Releases API, stdlib only)

Usage:
    python packaging/generate_manifests.py --sha256 <64-hex> [--version 1.2.3]
    python packaging/generate_manifests.py --fetch           # live release
    python packaging/generate_manifests.py --print            # stdout only

The committed manifests are exactly what this script renders for the
current release. CI (release.yml job "distribution-manifests") re-renders
them per tag so they never go stale.

Design rules (matching rex/updates.py):
- stdlib only (urllib, not httpx) so the script runs anywhere, including
  fresh CI runners with zero pip installs.
- Clear error message + exit code 2 on bad input; no tracebacks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

# ──────────────────────────────────────────────────────────────────────
# Static release facts (packaging identity, not build output)
# ──────────────────────────────────────────────────────────────────────

REPO = "huseinrosidstilllearn/rex-code"
REPO_URL = f"https://github.com/{REPO}"
GITHUB_API = f"https://api.github.com/repos/{REPO}/releases/latest"

# Package identity. winget-pkgs rule: <PublisherName>.<PackageName> where
# the publisher matches the "Apps & Features" entry produced by the Inno
# installer (rexcode.iss AppPublisher).
PACKAGE_ID = "RexCodeTeam.RexCode"
PUBLISHER = "Rex Code Team"
MONIKER = "rexcode"
APP_EXE = "rex.exe"
APP_NAME = "Rex Code"
SHORT_DESCRIPTION = "Autonomous AI coding agent — plan, build, and self-debug with a sandboxed tool layer"
LICENSE = "MIT"

# Inno silent switches. "addtopath" is unchecked by default in the wizard
# (rexcode.iss task list) — a silent winget install must opt in explicitly,
# otherwise `rex` is unreachable from PATH. "keepdata" preserves user data
# on uninstall, matching the wizard's checkedonce default.
INNO_TASKS = "addtopath,keepdata"
INNO_SILENT = "/SP- /VERYSILENT /SUPPRESSMSGBOXES /NORESTART"
INNO_SILENT_WITH_PROGRESS = "/SP- /SILENT /SUPPRESSMSGBOXES /NORESTART"

ROOT = Path(__file__).resolve().parent.parent
WINGET_DIR = ROOT / "packaging" / "winget"
SCOOP_DIR = ROOT / "packaging" / "scoop"
VERSION_RE = re.compile(r'__version__\s*=\s*"([^"]+)"')
APPID_RE = re.compile(r"AppId\s*=\s*\{\{([^}]+)\}")

# ──────────────────────────────────────────────────────────────────────
# Inputs
# ──────────────────────────────────────────────────────────────────────

def read_version(override: Optional[str] = None) -> str:
    """Version from rex/__init__.py (the project's single source of truth)."""
    if override:
        return override.strip()
    src = (ROOT / "rex" / "__init__.py").read_text(encoding="utf-8")
    match = VERSION_RE.search(src)
    if not match:
        raise SystemExit("error: __version__ not found in rex/__init__.py")
    return match.group(1)


def read_app_id() -> str:
    """Inno AppId GUID from rexcode.iss — becomes the winget ProductCode."""
    src = (ROOT / "installer" / "windows" / "rexcode.iss").read_text(encoding="utf-8")
    match = APPID_RE.search(src)
    if not match:
        raise SystemExit("error: AppId not found in rexcode.iss")
    return match.group(1).strip()


def _validate_sha256(value: str) -> str:
    value = value.strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise SystemExit(f"error: --sha256 must be 64 hex chars, got {value!r}")
    return value


def fetch_release_sha256(version: str) -> Tuple[str, Optional[str]]:
    """Ask the GitHub API for the published date + installer SHA256."""
    import urllib.request

    headers = {"User-Agent": "rex-code-manifest-generator"}
    try:
        with urllib.request.urlopen(urllib.request.Request(GITHUB_API, headers=headers), timeout=30) as resp:
            release = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — report, never traceback
        raise SystemExit(f"error: could not fetch {GITHUB_API}: {exc}") from exc

    # releases/latest may lag one API call behind a fresh tag; fall back to
    # the explicit tag so right-after-publish runs still succeed.
    if (release.get("tag_name") or "").lstrip("v") != version.lstrip("v"):
        tag_url = f"https://api.github.com/repos/{REPO}/releases/tags/v{version}"
        try:
            with urllib.request.urlopen(urllib.request.Request(tag_url, headers=headers), timeout=30) as resp:
                release = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(
                f"error: latest release is {release.get('tag_name')!r}, "
                f"expected v{version}; tag fallback failed: {exc}"
            ) from exc

    asset_name = f"RexCode-Setup-v{version}-x64.exe"
    asset = next((a for a in release.get("assets", []) if a.get("name") == asset_name), None)
    if asset is None:
        raise SystemExit(f"error: asset {asset_name} not found on the release")

    url = asset["browser_download_url"]
    print(f"downloading {url} ...", file=sys.stderr)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=300) as resp:
            digest = hashlib.sha256(resp.read()).hexdigest()
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"error: download failed: {exc}") from exc

    published = (release.get("published_at") or "")[:10] or None
    return digest, published


# ──────────────────────────────────────────────────────────────────────
# Renderers
# ──────────────────────────────────────────────────────────────────────

def asset_url(version: str) -> str:
    return f"{REPO_URL}/releases/download/v{version}/RexCode-Setup-v{version}-x64.exe"


def render_winget_installer(version: str, sha256: str, app_id: str, release_date: str) -> str:
    product_code = f"{{{app_id}}}_is1"
    return f"""# Generated by packaging/generate_manifests.py — do not edit by hand.
# yaml-language-server: $schema=https://aka.ms/winget-manifest.installer.1.9.0.schema.json

PackageIdentifier: {PACKAGE_ID}
PackageVersion: {version}
InstallerType: inno
InstallerSwitches:
  Silent: {INNO_SILENT}
  SilentWithProgress: {INNO_SILENT_WITH_PROGRESS}
  Custom: /TASKS={INNO_TASKS}
UpgradeBehavior: install
Commands:
- rex
ReleaseDate: {release_date}
ElevationRequirement: elevatesSelf
Installers:
- Architecture: x64
  Scope: machine
  InstallerUrl: {asset_url(version)}
  InstallerSha256: {sha256.upper()}
  ProductCode: {product_code}
ManifestType: installer
ManifestVersion: 1.9.0
"""


def render_winget_locale(version: str) -> str:
    return f"""# Generated by packaging/generate_manifests.py — do not edit by hand.
# yaml-language-server: $schema=https://aka.ms/winget-manifest.defaultLocale.1.9.0.schema.json

PackageIdentifier: {PACKAGE_ID}
PackageVersion: {version}
PackageLocale: en-US
Publisher: {PUBLISHER}
PublisherUrl: {REPO_URL}
PublisherSupportUrl: {REPO_URL}/issues
PackageName: {APP_NAME}
PackageUrl: {REPO_URL}
License: {LICENSE}
LicenseUrl: {REPO_URL}/blob/master/LICENSE
ShortDescription: {SHORT_DESCRIPTION}
Description: |-
  Rex Code is an autonomous AI coding agent for the terminal. Think of a goal,
  let Rex plan it, approve, and watch it build: a sandboxed tool layer, five
  sub-agent specialists, plugin system, voice input, and one-click installer
  with automatic updates.
Moniker: {MONIKER}
Tags:
- ai
- agent
- coding
- cli
- tui
- gemini
- llm
ReleaseNotesUrl: {REPO_URL}/releases/tag/v{version}
Documentations:
- DocumentLabel: Install Guide (English/Indonesian)
  DocumentUrl: {REPO_URL}/blob/master/PANDUAN-INSTALL.md
ManifestType: defaultLocale
ManifestVersion: 1.9.0
"""


def render_winget_version(version: str) -> str:
    return f"""# Generated by packaging/generate_manifests.py — do not edit by hand.
# yaml-language-server: $schema=https://aka.ms/winget-manifest.version.1.9.0.schema.json

PackageIdentifier: {PACKAGE_ID}
PackageVersion: {version}
DefaultLocale: en-US
ManifestType: version
ManifestVersion: 1.9.0
"""


def render_scoop(version: str, sha256: str) -> str:
    """Scoop manifest for the Inno installer. Canonical Inno pattern in
    official buckets (see keepass.json): plain URL + "innosetup": true —
    scoop extracts the {app} payload with 7-Zip without ever executing
    the installer; uninstaller leftovers (unins*.exe/dat) are dropped by
    scoop's Inno handling."""
    return json.dumps(
        {
            "version": version,
            "description": SHORT_DESCRIPTION,
            "homepage": REPO_URL,
            "license": {"identifier": LICENSE, "url": f"{REPO_URL}/blob/master/LICENSE"},
            "architecture": {
                "64bit": {
                    "url": asset_url(version),
                    "hash": sha256,
                }
            },
            "innosetup": True,
            "bin": [["rex.exe", "rex"]],
            "shortcuts": [["rex.exe", APP_NAME]],
            "checkver": "github",
            "autoupdate": {
                "architecture": {
                    "64bit": {
                        "url": asset_url("$version"),
                    }
                },
                "hash": {
                    "url": f"{REPO_URL}/releases/download/v$version/SHA256SUMS.txt",
                    "regex": "(?m)^$sha256.*?$basename",
                },
            },
        },
        indent=4,
        ensure_ascii=False,
    ) + "\n"


# ──────────────────────────────────────────────────────────────────────
# Write / print
# ──────────────────────────────────────────────────────────────────────

def write_manifests(version: str, sha256: str, release_date: str, app_id: str, print_only: bool = False) -> None:
    """Render all manifests; write them (LF, deterministic) or print only."""
    outputs = {
        "winget/RexCodeTeam.RexCode.installer.yaml": render_winget_installer(version, sha256, app_id, release_date),
        "winget/RexCodeTeam.RexCode.locale.en-US.yaml": render_winget_locale(version),
        "winget/RexCodeTeam.RexCode.yaml": render_winget_version(version),
        "scoop/rexcode.json": render_scoop(version, sha256),
    }
    for rel, content in outputs.items():
        if print_only:
            print(f"===== packaging/{rel} =====")
            print(content)
            continue
        target = ROOT / "packaging" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        # LF endings, no BOM, trailing newline — byte-stable for CI diffs.
        target.write_bytes(content.replace("\r\n", "\n").encode("utf-8"))
        print(f"wrote packaging/{rel}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha256", help="installer SHA256 (64 hex chars)")
    parser.add_argument("--fetch", action="store_true", help="fetch SHA256 + release date from GitHub Releases")
    parser.add_argument("--version", help="override rex/__init__.py version")
    parser.add_argument("--release-date", help="ReleaseDate override (YYYY-MM-DD); default: today UTC, or the release's published date with --fetch")
    parser.add_argument("--print", dest="print_only", action="store_true", help="render to stdout, write nothing")
    args = parser.parse_args(argv)

    version = read_version(args.version)
    app_id = read_app_id()

    if args.sha256:
        sha256 = _validate_sha256(args.sha256)
        release_date = args.release_date or datetime.now(timezone.utc).date().isoformat()
    elif args.fetch:
        sha256, fetched_date = fetch_release_sha256(version)
        release_date = args.release_date or fetched_date or datetime.now(timezone.utc).date().isoformat()
        print(f"installer sha256: {sha256}", file=sys.stderr)
    else:
        parser.error("one of --sha256 or --fetch is required")

    write_manifests(version, sha256, release_date, app_id, args.print_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

