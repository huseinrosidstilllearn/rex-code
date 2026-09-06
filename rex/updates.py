"""
rex.updates
===========
Auto-update checker for Rex Code.

On startup (background thread) Rex queries the GitHub Releases API for the
configured repository. When a newer version exists it:

1. Notifies the user (one dim line in the UI),
2. Optionally downloads the installer for the current platform
   (`auto_download`),
3. Optionally launches the installer and exits so rex.exe is not locked
   while it replaces itself (`auto_install`). Windows shows its own UAC
   prompt.

Design rules:
- **Never raise** — any network/file failure is a silent skip. A missing
  release, rate limiting, or being offline must never disturb startup.
- Check at most once per `check_interval_hours` (cache file under LOGS_DIR).
- Auto-install runs at most once per version number (anti-loop guard): if
  the user cancels the Inno wizard, Rex does not retry on every launch.

Security:
- Downloads only from the asset URLs returned by the official releases API
  (github.com / objects.githubusercontent.com over HTTPS).
- Strict asset-name pattern per platform; minimum size sanity check.
- No new dependencies (httpx is already a project dependency).
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import httpx

import rex
from rex.config import LOGS_DIR
from rex.logging_setup import log

CACHE_FILE = LOGS_DIR / "last_update_check.json"

# Asset-name patterns per platform (only these are ever downloaded).
_SETUP_RE = re.compile(r"^RexCode-Setup-v\d+\.\d+\.\d+-x64\.exe$", re.IGNORECASE)
_LINUX_RE = re.compile(r"^rex-linux-x64\.zip$", re.IGNORECASE)
_MACOS_RE = re.compile(r"^rex-macos-arm64\.zip$", re.IGNORECASE)
_CHECKSUMS_RE = re.compile(r"^SHA256SUMS\.txt$", re.IGNORECASE)

# A real installer is at least a few MB; anything smaller is suspicious.
_MIN_ASSET_BYTES = 1_000_000

_ALLOWED_ASSET_HOSTS = (
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
)


# ──────────────────────────────────────────────────────────────────────
# Version comparison
# ──────────────────────────────────────────────────────────────────────

def _parse_version(version: str) -> Tuple[int, ...]:
    """'v1.2.3-beta' -> (1, 2, 3). Non-numeric segments stop the tuple."""
    cleaned = version.strip().lower()
    if cleaned.startswith("v"):
        cleaned = cleaned[1:]
    cleaned = cleaned.split("-", 1)[0]
    parts: List[int] = []
    for segment in cleaned.split("."):
        if segment.isdigit():
            parts.append(int(segment))
        else:
            break
    return tuple(parts) if parts else (0,)


def compare_versions(a: str, b: str) -> int:
    """Return 1 if a > b, -1 if a < b, 0 if equal. Missing segments = 0."""
    va, vb = _parse_version(a), _parse_version(b)
    length = max(len(va), len(vb))
    va += (0,) * (length - len(va))
    vb += (0,) * (length - len(vb))
    if va > vb:
        return 1
    if va < vb:
        return -1
    return 0


# ──────────────────────────────────────────────────────────────────────
# GitHub Releases API
# ──────────────────────────────────────────────────────────────────────

def get_latest_release(repo: str, timeout: float = 5.0) -> Optional[Dict]:
    """
    Return the latest release JSON from GitHub, or None on any failure.
    Never raises.
    """
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        response = httpx.get(
            url,
            timeout=timeout,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"rex-code-updater/v{rex.__version__}",
            },
            follow_redirects=True,
        )
        if response.status_code != 200:
            log.debug(f"update check: HTTP {response.status_code} from {url}")
            return None
        data = response.json()
        return data if isinstance(data, dict) else None
    except Exception as exc:  # offline, timeout, bad JSON, ...
        log.debug(f"update check failed: {exc}")
        return None


def pick_asset(assets: List[Dict], platform_name: Optional[str] = None) -> Optional[Dict]:
    """
    Pick the release asset matching the current platform.
    platform_name is injectable for tests (sys.platform-like value).
    """
    plat = (platform_name or platform.system()).lower()
    if plat.startswith("win"):
        pattern = _SETUP_RE
    elif plat == "darwin":
        pattern = _MACOS_RE
    else:
        pattern = _LINUX_RE

    for asset in assets:
        name = str(asset.get("name", ""))
        size = int(asset.get("size") or 0)
        url = str(asset.get("browser_download_url", ""))
        if pattern.match(name) and size >= _MIN_ASSET_BYTES and url.startswith("https://"):
            if any(host in url for host in _ALLOWED_ASSET_HOSTS):
                return asset
    return None


# ──────────────────────────────────────────────────────────────────────
# Download
# ──────────────────────────────────────────────────────────────────────

def download_asset(url: str, dest_dir: Path, timeout: float = 60.0) -> Optional[Path]:
    """
    Stream the asset to dest_dir. Writes to '<name>.part' first and renames
    atomically so a crash never leaves a half installer with a good name.
    Removes any older installer in dest_dir afterwards (keep only latest).
    Returns the final path, or None on any failure. Never raises.
    """
    name = url.rsplit("/", 1)[-1]
    if not _asset_name_allowed(name):
        return None
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        final_path = dest_dir / name
        part_path = dest_dir / (name + ".part")
        bytes_seen = 0
        with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as response:
            if response.status_code != 200:
                return None
            with open(part_path, "wb") as fh:
                for chunk in response.iter_bytes():
                    bytes_seen += len(chunk)
                    fh.write(chunk)
        if bytes_seen < _MIN_ASSET_BYTES:
            part_path.unlink(missing_ok=True)
            return None
        # Keep only one installer: drop previous artifacts first.
        for old in dest_dir.iterdir():
            if old.is_file() and old != part_path and _asset_name_allowed(old.name):
                old.unlink(missing_ok=True)
        part_path.replace(final_path)
        return final_path
    except Exception as exc:
        log.debug(f"update download failed: {exc}")
        try:
            (dest_dir / (name + ".part")).unlink(missing_ok=True)
        except Exception:
            pass
        return None


def _asset_name_allowed(name: str) -> bool:
    return bool(
        _SETUP_RE.match(name)
        or _LINUX_RE.match(name)
        or _MACOS_RE.match(name)
        or _CHECKSUMS_RE.match(name)
    )


# ──────────────────────────────────────────────────────────────────────
# Checksum verification (SHA256SUMS.txt published by CI)
# ──────────────────────────────────────────────────────────────────────

def _download_raw(url: str, dest_dir: Path, timeout: float = 60.0) -> Optional[Path]:
    """Download a small companion file (e.g. SHA256SUMS.txt) without the
    min-size rule that applies to installers. Never raises."""
    name = url.rsplit("/", 1)[-1]
    if not _asset_name_allowed(name):
        return None
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        response = httpx.get(url, timeout=timeout, follow_redirects=True)
        if response.status_code != 200 or not response.content:
            return None
        path = dest_dir / name
        path.write_bytes(response.content)
        return path
    except Exception as exc:
        log.debug(f"update: checksum download failed: {exc}")
        return None


def download_checksums(release: Dict, dest_dir: Path, timeout: float = 60.0) -> Optional[Path]:
    """Download SHA256SUMS.txt from the release. None when unavailable."""
    for asset in release.get("assets") or []:
        name = str(asset.get("name", ""))
        url = str(asset.get("browser_download_url", ""))
        if _CHECKSUMS_RE.match(name) and url.startswith("https://"):
            if any(host in url for host in _ALLOWED_ASSET_HOSTS):
                return _download_raw(url, dest_dir, timeout)
    return None


def verify_checksum(installer_path: Path, checksums_path: Path) -> Optional[bool]:
    """
    Compare the installer's SHA256 against SHA256SUMS.txt.
    True = verified, False = MISMATCH (treat as tampered/corrupt),
    None = cannot verify (file missing, no entry for this asset).
    Never raises.
    """
    try:
        if not installer_path.is_file() or not checksums_path.is_file():
            return None
        digest = hashlib.sha256(installer_path.read_bytes()).hexdigest()
        for line in checksums_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            expected, filename = parts
            filename = filename.lstrip("*").strip()
            if filename.lower() == installer_path.name.lower():
                return expected.strip().lower() == digest
        return None
    except Exception as exc:
        log.debug(f"update: checksum verify failed: {exc}")
        return None


# ──────────────────────────────────────────────────────────────────────
# Install
# ──────────────────────────────────────────────────────────────────────

def install_update(installer_path: Path) -> bool:
    """
    Launch the installer (Windows shows its own UAC prompt).
    Returns True when the launch was handed to the OS. Never raises.
    """
    try:
        if not installer_path.is_file():
            return False
        if os.name != "nt":
            log.debug("auto-install is only supported on Windows")
            return False
        os.startfile(str(installer_path))  # noqa: S606 - user-initiated updater
        return True
    except Exception as exc:
        log.debug(f"auto-install failed: {exc}")
        return False


# ──────────────────────────────────────────────────────────────────────
# Cache (rate-limit friendliness + anti-loop)
# ──────────────────────────────────────────────────────────────────────

def _read_cache() -> Dict:
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_cache(data: Dict) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def _cache_fresh(cache: Dict, interval_hours: float) -> bool:
    checked_at = cache.get("checked_at", 0)
    try:
        age_hours = (time.time() - float(checked_at)) / 3600.0
    except (TypeError, ValueError):
        return False
    return age_hours < float(interval_hours)


# ──────────────────────────────────────────────────────────────────────
# Orchestrator
# ──────────────────────────────────────────────────────────────────────

def check_for_update(settings: Dict, current_version: Optional[str] = None) -> Optional[str]:
    """
    Query GitHub for a newer version. Returns the newer version string or
    None (also None when up-to-date, disabled, or on any failure).
    Honors the daily cache. Never raises.
    """
    if not settings.get("enabled", True):
        return None
    repo = str(settings.get("repo") or "").strip()
    if not repo:
        return None

    interval = float(settings.get("check_interval_hours", 24))
    cache = _read_cache()
    if _cache_fresh(cache, interval):
        cached_newer = str(cache.get("newer_version") or "")
        if cached_newer and compare_versions(cached_newer, current_version or rex.__version__) > 0:
            return cached_newer
        return None

    release = get_latest_release(repo, timeout=float(settings.get("timeout_sec", 5)))
    # Write cache even on failure: avoids hammering a dead network on
    # every startup. Failure results re-check after the full interval.
    latest = str(release.get("tag_name") or "") if release else ""
    if latest.startswith("v") or latest.startswith("V"):
        latest = latest[1:]  # normalize 'v0.2.0' -> '0.2.0'
    newer = latest if (latest and compare_versions(latest, current_version or rex.__version__) > 0) else ""
    _write_cache({"checked_at": time.time(), "latest": latest, "newer_version": newer})
    return newer or None


def maybe_update(
    settings: Dict,
    on_notice: Callable[[str], None],
    on_ready_to_install: Optional[Callable[[Path], None]] = None,
    current_version: Optional[str] = None,
) -> None:
    """
    Full update flow for one startup. Designed to run on a background
    thread. Never raises; every failure path is a silent skip.

    on_notice(text)            — UI hook for the "update available" line.
    on_ready_to_install(path)  — UI hook when the installer is on disk and
                                 auto-install is enabled (launch + exit).
    """
    try:
        if not settings.get("enabled", True):
            return
        version = current_version or rex.__version__
        newer = check_for_update(settings, current_version=version)
        if not newer:
            return

        on_notice(f"Pembaruan tersedia: v{newer} (terpasang: v{version})")

        if not settings.get("auto_download", False):
            repo = str(settings.get("repo") or "")
            on_notice(f"Unduh manual: https://github.com/{repo}/releases/latest")
            return

        download_dir = Path(str(settings.get("download_dir") or (LOGS_DIR.parent / "downloads")))
        release = get_latest_release(str(settings.get("repo") or ""))
        if not release:
            return
        asset = pick_asset(release.get("assets") or [])
        if not asset:
            on_notice(f"Pembaruan v{newer} tersedia (aset untuk OS ini belum ada).")
            return

        on_notice(f"Mengunduh v{newer}...")
        installer = download_asset(
            str(asset.get("browser_download_url", "")), download_dir
        )
        if not installer:
            return

        # Integrity gate: verify SHA256 before anything may execute the file.
        sums = download_checksums(release, download_dir)
        if sums is not None:
            verdict = verify_checksum(installer, sums)
            if verdict is False:
                try:
                    installer.unlink(missing_ok=True)
                except Exception:
                    pass
                log.warning("update: checksum MISMATCH — installer discarded")
                on_notice("Unduhan gagal verifikasi checksum dan telah dibuang. Unduh manual dari halaman Releases.")
                return
            if verdict is None:
                # Checksums file exists but no entry for this asset -> fail-safe.
                log.warning("update: entri checksum tidak ditemukan — auto-install dilewati")
                on_notice(f"Installer v{newer} siap: {installer.name} (checksum tidak diverifikasi — jalankan manual bila yakin)")
                return
            log.debug("update: checksum verified OK")
        else:
            # No SHA256SUMS.txt on this release: do not auto-execute. Fail-safe.
            log.warning("update: SHA256SUMS.txt tidak tersedia — auto-install dilewati")
            on_notice(f"Installer v{newer} siap: {installer.name} (rilis belum menyertakan checksum — jalankan manual)")
            return

        on_notice(f"Installer v{newer} siap: {installer.name}")

        cache = _read_cache()
        if cache.get("installed_version") == newer:
            return  # anti-loop: already attempted for this version
        if settings.get("auto_install", False) and on_ready_to_install is not None:
            cache["installed_version"] = newer
            _write_cache(cache)
            on_ready_to_install(installer)
    except Exception as exc:  # absolute guard: updates must never crash startup
        log.debug(f"update flow error: {exc}")
