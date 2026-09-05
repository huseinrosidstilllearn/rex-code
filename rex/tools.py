"""
rex.tools
Execution layer for Rex Code.
Enforces mode permissions (Plan Mode = read only, Build Mode = write + execute).
"""

import os
import re
import subprocess
import unicodedata
from pathlib import Path
from typing import Dict, Any, List, Optional
from rex.config import WORKSPACE_DIR, WORKFLOWS_DIR, get_active_mode, load_config
from rex.shell import build_command_argv

SENSITIVE_FILENAMES = {".env", "config.json", "credentials.json", "credential.json", "secrets.json"}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".keystore"}


def resolve_path(rel_path: str, base_dir: Path = WORKSPACE_DIR) -> Optional[Path]:
    """
    Safely resolve a path inside the workspace or project directory.
    """
    if not isinstance(rel_path, str) or not rel_path.strip():
        return None
    cleaned = rel_path.strip()
    target = (base_dir / cleaned).resolve()
    root = base_dir.resolve()
    return target if target.is_relative_to(root) else None


def _target(path: str) -> Optional[Path]:
    normalized = str(path).replace("\\", "/")
    if normalized.lower().startswith("workflows/"):
        return resolve_path(normalized[len("workflows/"):], WORKFLOWS_DIR)
    return resolve_path(path, WORKSPACE_DIR)


def _is_sensitive(target: Optional[Path]) -> bool:
    return target is None or target.name.lower() in SENSITIVE_FILENAMES or target.suffix.lower() in SENSITIVE_SUFFIXES

def read_file(path: str) -> str:
    """Membaca isi file di dalam workspace."""
    target = _target(path)
    if _is_sensitive(target):
        return "DIBLOKIR KEAMANAN: path di luar workspace atau file sensitif."
    if not target.exists():
        return f"Error: File '{path}' tidak ditemukan."
    try:
        limit = max(100, int(load_config().get("file_read_max_chars", 20000)))
        with open(target, "rb") as raw:
            if b"\x00" in raw.read(1024):
                return "DIBLOKIR KEAMANAN: file biner tidak dapat dibaca."
        with open(target, "r", encoding="utf-8") as f:
            content = f.read(limit + 1)
        return _truncate_output(content, limit)
    except Exception as e:
        return f"Error saat membaca file: {str(e)}"

def write_file(path: str, content: str) -> str:
    """Menulis atau menimpa isi file baru di dalam workspace (Hanya aktif di Mode Build)."""
    mode = get_active_mode()
    if mode == "plan":
        return "TIDAK DIIZINKAN: Anda sedang berada di Mode Plan. Penulisan file hanya diizinkan setelah pengguna beralih ke Mode Build."

    target = _target(path)
    if _is_sensitive(target):
        return "DIBLOKIR KEAMANAN: path di luar workspace atau file sensitif."

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Berhasil menulis file: {target.relative_to(WORKSPACE_DIR.parent)}"
    except Exception as e:
        return f"Error saat menulis file: {str(e)}"

def edit_file(path: str, target_content: str, replacement_content: str) -> str:
    """Mengganti potongan teks tertentu di dalam file (Hanya aktif di Mode Build)."""
    mode = get_active_mode()
    if mode == "plan":
        return "TIDAK DIIZINKAN: Anda sedang berada di Mode Plan. Modifikasi file hanya diizinkan di Mode Build."

    target = _target(path)
    if _is_sensitive(target):
        return "DIBLOKIR KEAMANAN: path di luar workspace atau file sensitif."
    if not target.exists():
        return f"Error: File '{path}' tidak ditemukan."
    try:
        with open(target, "r", encoding="utf-8") as f:
            data = f.read()
        if target_content not in data:
            return "Error: Potongan target_content tidak ditemukan secara persis di dalam file."
        new_data = data.replace(target_content, replacement_content, 1)
        with open(target, "w", encoding="utf-8") as f:
            f.write(new_data)
        return f"Berhasil mengedit file: {target.name}"
    except Exception as e:
        return f"Error saat mengedit file: {str(e)}"

def list_dir(path: str = ".") -> str:
    """Melihat daftar file dan folder yang ada di dalam workspace."""
    target = _target(path)
    if target is None:
        return "DIBLOKIR KEAMANAN: path di luar workspace."
    if not target.exists():
        return f"Direktori '{path}' tidak ditemukan."
    try:
        items = []
        for item in target.iterdir():
            icon = "ðŸ“" if item.is_dir() else "ðŸ“„"
            items.append(f"{icon} {item.name}")
        return "\n".join(items) if items else "(Direktori kosong)"
    except Exception as e:
        return f"Error saat membaca direktori: {str(e)}"

def search_files(query: str, path: str = ".") -> str:
    """Mencari file yang mengandung kata atau nama tertentu di dalam workspace."""
    target = _target(path)
    if target is None:
        return "DIBLOKIR KEAMANAN: path di luar workspace."
    if not target.exists():
        return f"Direktori '{path}' tidak ditemukan."
    results = []
    try:
        for root, dirs, files in os.walk(target):
            dirs[:] = [item for item in dirs if not item.startswith(".")]
            for file in files:
                filepath = Path(root) / file
                if _is_sensitive(filepath):
                    continue
                if query.lower() in file.lower():
                    results.append(f"Nama cocok: {filepath.relative_to(WORKSPACE_DIR.parent)}")
                    continue
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        if query.lower() in f.read(20001).lower():
                            results.append(f"Konten cocok: {filepath.relative_to(WORKSPACE_DIR.parent)}")
                except Exception:
                    pass
        return "\n".join(results) if results else f"Tidak ditemukan kecocokan untuk '{query}'."
    except Exception as e:
        return f"Error saat mencari file: {str(e)}"


def search_content(query: str, path: str = ".") -> str:
    """Cari teks dan nomor baris dalam file teks workspace."""
    if not isinstance(query, str) or not query:
        return "Error: Query pencarian kosong."
    target = _target(path)
    if target is None or not target.exists():
        return "DIBLOKIR KEAMANAN: path tidak valid atau di luar workspace."
    results = []
    files = [target] if target.is_file() else target.rglob("*")
    for filepath in files:
        if not filepath.is_file() or _is_sensitive(filepath) or any(part.startswith(".") for part in filepath.relative_to(WORKSPACE_DIR.parent).parts):
            continue
        try:
            with open(filepath, "r", encoding="utf-8") as file:
                for line_number, line in enumerate(file, 1):
                    if query.lower() in line.lower():
                        results.append(f"{filepath.relative_to(WORKSPACE_DIR.parent)}:{line_number}: {line.strip()[:300]}")
                        if len(results) >= 100:
                            return "\n".join(results) + "\n...[hasil dibatasi]"
        except OSError:
            continue
    return "\n".join(results) if results else f"Tidak ditemukan kecocokan untuk '{query}'."


def delete_file(path: str) -> str:
    """Hapus satu file di workspace pada Mode Build."""
    if get_active_mode() == "plan":
        return "TIDAK DIIZINKAN: Penghapusan file hanya diizinkan di Mode Build."
    target = _target(path)
    if _is_sensitive(target):
        return "DIBLOKIR KEAMANAN: path di luar workspace atau file sensitif."
    if not target.exists() or not target.is_file():
        return f"Error: File '{path}' tidak ditemukan."
    try:
        target.unlink()
        return f"Berhasil menghapus file: {target.relative_to(WORKSPACE_DIR.parent)}"
    except OSError as error:
        return f"Error saat menghapus file: {error}"

SECRET_ENV_MARKERS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "PRIVATE_KEY", "CREDENTIAL")

ALWAYS_BLOCKED_COMMANDS = (
    (r"(^|[;&|]\s*)(iex|invoke-expression)\b", "eksekusi PowerShell dinamis"),
    (r"\s-(encodedcommand|enc|e)\b", "perintah PowerShell terenkripsi"),
    (r"\b(set-executionpolicy|stop-computer|restart-computer|shutdown|poweroff|reboot)\b", "perubahan sistem"),
    (r"\b(format-volume|clear-disk|initialize-disk|cipher\s+/w)\b", "operasi disk destruktif"),
    (r"\brm\s+-r[f]?\s+[/~]", "penghapusan direktori sistem"),
    (r"\bsudo\b", "eskalasi privilege"),
    (r"\bdd\s+if=/dev/zero", "penimpaan disk"),
    (r"\bchmod\s+-R\s+777\s+/", "permission massal di root"),
    (r"\b(curl|wget)\b[^;&|]*\|\s*(?:sudo\s+)?(?:ba)?sh\b", "eksekusi skrip jarak jauh"),
    (r":\(\)\s*\{\s*:\|:&\s*\}\s*;", "fork bomb"),
    (r"\breg(?:\.exe)?\s+delete\b", "penghapusan registry"),
    (r"\bnet(?:\.exe)?\s+(user|localgroup)\b", "perubahan akun sistem"),
    (r"(?:\$env:|\benv:)[^\s;&|]*(api[_-]?key|token|secret|password|private[_-]?key|credential)", "akses secret environment"),
    (r"(?:^|[\s'\"\\/])\.env(?:\s|$|[;&|])", "akses file secret .env"),
    (r"(?:^|[\s'\"\\/])config\.json(?:\s|$|[;&|])", "akses konfigurasi proyek"),
)

UNSAFE_PATH = re.compile(r"(?:^|[\s'\"=])(?:[a-z]:[\\/]|\\\\|\.\.[\\/])", re.IGNORECASE)


def _normalized_command(command: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", command).split())


def _blocked_reason(command: str) -> str | None:
    normalized = _normalized_command(command)
    for pattern, reason in ALWAYS_BLOCKED_COMMANDS:
        if re.search(pattern, normalized, re.IGNORECASE):
            return reason
    if UNSAFE_PATH.search(normalized):
        return "path absolut atau traversal di luar workspace"
    return None


def _sanitized_environment() -> dict:
    return {
        key: value for key, value in os.environ.items()
        if not any(marker in key.upper() for marker in SECRET_ENV_MARKERS)
    }


def _truncate_output(output: str, limit: int) -> str:
    if len(output) <= limit:
        return output
    suffix = "\n\n[OUTPUT DIPOTONG]"
    return output[:max(0, limit - len(suffix))] + suffix


def run_command(command: str) -> str:
    """Menjalankan perintah PowerShell di direktori workspace (Hanya aktif di Mode Build)."""
    mode = get_active_mode()
    if mode == "plan":
        return "TIDAK DIIZINKAN: Anda sedang berada di Mode Plan. Eksekusi terminal hanya diizinkan di Mode Build."

    if not isinstance(command, str) or not command.strip():
        return "Error: Perintah kosong."

    blocked_reason = _blocked_reason(command)
    if blocked_reason:
        return f"DIBLOKIR KEAMANAN: {blocked_reason}."

    cfg = load_config()
    timeout = max(1, int(cfg.get("terminal_timeout_sec", 45)))
    output_limit = max(100, int(cfg.get("terminal_output_max_chars", 8000)))
    allowlist = {str(item).lower() for item in cfg.get("command_allowlist", [])}
    executable_match = re.match(r"^\s*(?:&\s*)?[\"']?([^\s\"']+)", _normalized_command(command))
    executable = Path(executable_match.group(1)).stem.lower() if executable_match else ""
    non_standard = bool(allowlist and executable not in allowlist)

    try:
        # Execute in workspace directory
        res = subprocess.run(
            build_command_argv(command),
            cwd=WORKSPACE_DIR,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_sanitized_environment(),
        )
        stdout = res.stdout.strip()
        stderr = res.stderr.strip()
        code = res.returncode

        output = []
        if stdout:
            output.append(f"[STDOUT]:\n{stdout}")
        if stderr:
            output.append(f"[STDERR - EXIT CODE {code}]:\n{stderr}")
        if not stdout and not stderr:
            output.append(f"(Perintah selesai tanpa output teks. Exit Code: {code})")
        if non_standard:
            output.insert(0, f"[PERINTAH NON-STANDAR: {executable or 'tidak diketahui'}]")
        return _truncate_output("\n\n".join(output), output_limit)
    except subprocess.TimeoutExpired:
        return f"Error: Perintah melampaui batas waktu (timeout {timeout} detik)."
    except Exception as e:
        return f"Error eksekusi: {str(e)}"


# --- Git Auto-Publish Tools -------------------------------------------------

DEFAULT_SECRET_PATTERNS = (
    r"ghp_[A-Za-z0-9]{20,}",
    r"github_pat_[A-Za-z0-9_]{20,}",
    r"AIza[A-Za-z0-9_-]{30,}",
    r"sk-[A-Za-z0-9]{20,}",
    r"BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY",
)


def _run_git(args, cwd, timeout):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def git_status() -> str:
    """Ringkasan status git: branch, perubahan staged/unstaged/untracked. Aktif di PLAN & BUILD."""
    try:
        result = _run_git(["status", "--short", "--branch"], cwd=Path.cwd(), timeout=15)
    except subprocess.TimeoutExpired:
        return "Error: git status timeout."
    except FileNotFoundError:
        return "Error: git tidak ditemukan di PATH."
    if result.returncode != 0:
        return f"Error git status: {result.stderr.strip() or 'unknown'}"
    return result.stdout.strip() or "Working tree bersih, tidak ada perubahan."


def git_publish(message: str) -> str:
    """Commit semua perubahan lalu push ke origin/HEAD (Hanya Mode Build)."""
    if get_active_mode() == "plan":
        return "TIDAK DIIZINKAN: git_publish hanya di Mode Build."

    if not isinstance(message, str) or not message.strip():
        return "Error: pesan commit kosong."

    cfg = load_config()
    if not cfg.get("git_publish_enabled", True):
        return "DIBLOKIR: git_publish_enabled=false di config.json."

    repo_root = Path(__file__).resolve().parent.parent
    push_timeout = max(10, int(cfg.get("git_publish_timeout_sec", 120)))
    max_files = max(1, int(cfg.get("git_publish_max_files", 50)))
    patterns = tuple(cfg.get("git_publish_block_patterns", list(DEFAULT_SECRET_PATTERNS)))
    if not isinstance(patterns, (list, tuple)):
        patterns = DEFAULT_SECRET_PATTERNS

    # 1. Pastikan ada remote origin
    try:
        remote = _run_git(["remote", "get-url", "origin"], cwd=repo_root, timeout=10)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return f"Error: {exc}"
    if remote.returncode != 0:
        return "Error: remote 'origin' belum dikonfigurasi."

    # 2. Pastikan ada perubahan
    try:
        status = _run_git(["status", "--porcelain"], cwd=repo_root, timeout=10)
    except subprocess.TimeoutExpired:
        return "Error: git status timeout."
    if status.returncode != 0:
        return f"Error git status: {status.stderr.strip()}"
    if not status.stdout.strip():
        return "Tidak ada perubahan untuk di-commit."

    changed_files = [line for line in status.stdout.splitlines() if line.strip()]
    if len(changed_files) > max_files:
        return (
            f"DIBLOKIR: {len(changed_files)} file berubah, melebihi batas "
            f"git_publish_max_files={max_files}. Commit manual jika ini disengaja."
        )

    # 3. Stage semua
    add = _run_git(["add", "-A"], cwd=repo_root, timeout=30)
    if add.returncode != 0:
        return f"Error git add: {add.stderr.strip()}"

    # 4. Scan secret SEBELUM commit (file staged)
    diff_check = _run_git(
        ["diff", "--cached", "--no-color"],
        cwd=repo_root,
        timeout=30,
    )
    if diff_check.returncode != 0:
        return f"Error git diff: {diff_check.stderr.strip()}"
    for pattern in patterns:
        match = re.search(pattern, diff_check.stdout, re.IGNORECASE)
        if match:
            return f"BLOKIR KEAMANAN: pola '{pattern}' terdeteksi di staged diff: {match.group(0)[:40]}..."

    # 5. Commit
    safe_message = message.strip().replace("\n", " ")[:200]
    commit = _run_git(
        ["commit", "-m", safe_message],
        cwd=repo_root,
        timeout=30,
    )
    if commit.returncode != 0:
        return f"Error git commit: {commit.stderr.strip() or commit.stdout.strip()}"

    # 6. Push
    push = _run_git(
        ["push", "origin", "HEAD"],
        cwd=repo_root,
        timeout=push_timeout,
    )
    if push.returncode != 0:
        return f"Error git push: {push.stderr.strip() or push.stdout.strip()}"

    push_url = remote.stdout.strip()
    return f"Berhasil publish '{safe_message}' -> {push_url}"



# Schema definitions for LLM Tool Calling
TOOL_DEFINITIONS = [
    {
        "name": "read_file",
        "description": "Membaca isi file di workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Nama atau path relatif file (misal: app.py, index.html)"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "Menulis atau membuat file baru di workspace (Hanya aktif di Mode Build).",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relatif file yang akan dibuat/ditulis"},
                "content": {"type": "string", "description": "Isi lengkap kode atau teks file"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "edit_file",
        "description": "Mengganti teks tertentu di dalam file yang sudah ada (Hanya aktif di Mode Build).",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path file yang ingin diedit"},
                "target_content": {"type": "string", "description": "Teks persis yang ingin diganti"},
                "replacement_content": {"type": "string", "description": "Teks baru pengganti"}
            },
            "required": ["path", "target_content", "replacement_content"]
        }
    },
    {
        "name": "list_dir",
        "description": "Melihat daftar file dan folder di dalam workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path folder yang ingin dilihat, default '.'"}
            }
        }
    },
    {
        "name": "search_files",
        "description": "Mencari file yang mengandung kata atau query tertentu.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Kata kunci yang dicari"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "delete_file",
        "description": "Menghapus satu file di workspace (Hanya aktif di Mode Build).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Path relatif file yang akan dihapus"}
        }, "required": ["path"]}
    },
    {
        "name": "search_content",
        "description": "Mencari teks beserta nomor baris dalam file workspace.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "path": {"type": "string", "description": "Folder relatif, default '.'"}
        }, "required": ["query"]}
    },
    {
        "name": "run_command",
        "description": "Menjalankan perintah PowerShell di workspace untuk menguji script, install modul, atau run server (Hanya aktif di Mode Build).",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Perintah PowerShell (misal: python main.py, pip install flask)"}
            },
            "required": ["command"]
        }
    },
    {
        "name": "git_status",
        "description": "Melihat ringkasan status git (branch, staged/unstaged/untracked). Aktif di PLAN & BUILD.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "git_publish",
        "description": "Commit semua perubahan lalu push ke origin (Hanya Mode Build). Memindai diff staged untuk pola rahasia sebelum commit.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Pesan commit (wajib, singkat & deskriptif)"}
            },
            "required": ["message"]
        }
    }
]

TOOL_REGISTRY = {
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "list_dir": list_dir,
    "search_files": search_files,
    "search_content": search_content,
    "delete_file": delete_file,
    "run_command": run_command,
    "git_status": git_status,
    "git_publish": git_publish,
}
