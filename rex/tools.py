"""
rex.tools
Execution layer for Rex Code.
Enforces mode permissions (Plan Mode = read only, Build Mode = write + execute).
"""

import os
import re
import subprocess
import threading
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional
from rex.config import WORKSPACE_DIR, WORKFLOWS_DIR, get_active_mode, load_config
from rex.approval import request_approval, summarize_action
from rex import checkpoints as _checkpoints
from rex import todos as _todos
from rex import diffs as _diffs
from rex.websearch import web_search, web_fetch

def _checkpoint_before(action: str, summary: str) -> None:
    """Snapshot workspace before a destructive action. Never blocks."""
    try:
        _checkpoints.snapshot(_checkpoints.label_for_action(action, summary))
    except Exception:
        pass
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
    if not request_approval("write_file", summarize_action("write_file", {"path": path})):
        return f"DITOLAK PENGGUNA: penulisan '{path}' tidak disetujui. Jangan coba lagi tanpa instruksi baru."
    _checkpoint_before("write_file", summarize_action("write_file", {"path": path}))

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
    if not request_approval("edit_file", summarize_action("edit_file", {"path": path})):
        return f"DITOLAK PENGGUNA: edit '{path}' tidak disetujui. Jangan coba lagi tanpa instruksi baru."
    _checkpoint_before("edit_file", summarize_action("edit_file", {"path": path}))
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
    if not request_approval("delete_file", summarize_action("delete_file", {"path": path})):
        return f"DITOLAK PENGGUNA: penghapusan '{path}' tidak disetujui. Jangan coba lagi tanpa instruksi baru."
    _checkpoint_before("delete_file", summarize_action("delete_file", {"path": path}))
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

    if not request_approval("run_command", summarize_action("run_command", {"command": command})):
        return "DITOLAK PENGGUNA: eksekusi perintah ini tidak disetujui. Jangan coba lagi tanpa instruksi baru."
    _checkpoint_before("run_command", summarize_action("run_command", {"command": command}))

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


# --- Background shell tasks -------------------------------------------------
# Long-running commands (dev servers, builds, test suites) started detached
# from the agent round. Same start-time sandbox as run_command: plan gate,
# denylist scan, approval gate + checkpoint. Output streams to a log file
# under logs/bg_tasks/ and is tailed by task_output. Tasks live for the
# current process only (TUI/CLI session).

BG_TASKS_DIRNAME = "bg_tasks"
MAX_BG_TASKS = 8
BG_OUTPUT_MAX_CHARS = 8000

_bg_lock = threading.RLock()
_bg_tasks: Dict[str, Dict[str, Any]] = {}


def _bg_dir() -> Path:
    from rex.config import LOGS_DIR
    directory = Path(LOGS_DIR) / BG_TASKS_DIRNAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _bg_watch(task_id: str) -> None:
    """Thread body: wait for the process, then finalize the entry."""
    entry = _bg_tasks[task_id]
    try:
        code = entry["proc"].wait()
    except Exception:
        code = -1
    with _bg_lock:
        entry["returncode"] = code
        entry["finished_at"] = time.time()
        if entry.get("killed"):
            entry["status"] = "killed"
        else:
            entry["status"] = "finished" if code == 0 else "failed"


def run_command_bg(command: str) -> str:
    """Memulai perintah jangka panjang di background (Hanya Mode Build)."""
    mode = get_active_mode()
    if mode == "plan":
        return "TIDAK DIIZINKAN: Anda sedang berada di Mode Plan. Eksekusi terminal hanya diizinkan di Mode Build."

    if not isinstance(command, str) or not command.strip():
        return "Error: Perintah kosong."

    blocked_reason = _blocked_reason(command)
    if blocked_reason:
        return f"DIBLOKIR KEAMANAN: {blocked_reason}."

    summary = f"background: {command}"
    if not request_approval("run_command", summarize_action("run_command", {"command": summary})):
        return "DITOLAK PENGGUNA: eksekusi background ini tidak disetujui. Jangan coba lagi tanpa instruksi baru."
    _checkpoint_before("run_command", summarize_action("run_command", {"command": summary}))

    with _bg_lock:
        active = sum(1 for item in _bg_tasks.values() if item["status"] == "running")
        if active >= MAX_BG_TASKS:
            return (
                f"Error: sudah ada {active} task background berjalan (maks {MAX_BG_TASKS}). "
                "Pantau/akhiri dengan task_output atau task_kill dulu."
            )
        task_id = f"bg_{uuid.uuid4().hex[:6]}"

    log_path = _bg_dir() / f"{task_id}.log"
    try:
        with open(log_path, "w", encoding="utf-8", errors="replace") as sink:
            proc = subprocess.Popen(
                build_command_argv(command),
                cwd=WORKSPACE_DIR,
                stdout=sink,
                stderr=subprocess.STDOUT,
                text=True,
                env=_sanitized_environment(),
            )
    except Exception as exc:
        return f"Error start background: {str(exc)}"

    entry = {
        "id": task_id,
        "command": command,
        "proc": proc,
        "status": "running",
        "killed": False,
        "returncode": None,
        "started_at": time.time(),
        "finished_at": None,
        "log": str(log_path),
    }
    with _bg_lock:
        _bg_tasks[task_id] = entry
    thread = threading.Thread(target=_bg_watch, args=(task_id,), daemon=True)
    entry["thread"] = thread
    thread.start()

    cfg = load_config()
    allowlist = {str(item).lower() for item in cfg.get("command_allowlist", [])}
    executable_match = re.match(r"^\s*(?:&\s*)?[\"']?([^\s\"']+)", _normalized_command(command))
    executable = Path(executable_match.group(1)).stem.lower() if executable_match else ""
    hint = f"\n[PERINTAH NON-STANDAR: {executable or 'tidak diketahui'}]" if allowlist and executable not in allowlist else ""
    return (
        f"[{task_id}] berjalan di background{hint}. "
        f"Pantau dengan task_output(task_id=\"{task_id}\") atau akhiri dengan task_kill(task_id=\"{task_id}\")."
    )


def _bg_find(task_id: str) -> Optional[dict]:
    with _bg_lock:
        return _bg_tasks.get(str(task_id or "").strip())


def _bg_tail(entry: dict) -> str:
    try:
        content = Path(entry["log"]).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(output belum tersedia)"
    content = content.strip()
    if not content:
        return "(belum ada output)"
    if len(content) > BG_OUTPUT_MAX_CHARS:
        content = content[-BG_OUTPUT_MAX_CHARS:]
        return "...[DIPOTONG]\n" + content
    return content


def task_output(task_id: str = "", wait_seconds: int = 0) -> str:
    """Baca output terbaru sebuah task background (boleh di PLAN & BUILD)."""
    entry = _bg_find(task_id)
    if entry is None:
        with _bg_lock:
            known = sorted(_bg_tasks) or ["(kosong)"]
        return f"Error: task '{task_id}' tidak ditemukan. Task tersedia: {', '.join(known)}"

    try:
        wait = max(0, min(30, int(wait_seconds or 0)))
    except (TypeError, ValueError):
        wait = 0
    deadline = time.time() + wait
    while entry["status"] == "running" and time.time() < deadline:
        time.sleep(0.1)

    elapsed = (entry["finished_at"] or time.time()) - entry["started_at"]
    header = f"[{task_id}] status={entry['status']} ({elapsed:.1f}s) — {entry['command'][:100]}"
    if entry["status"] == "running" and wait > 0:
        header += " [masih berjalan setelah menunggu]"
    if entry["returncode"] is not None:
        header += f" exit={entry['returncode']}"
    return f"{header}\n\n{_bg_tail(entry)}"


def task_kill(task_id: str = "") -> str:
    """Hentikan sebuah task background (Hanya Mode Build)."""
    entry = _bg_find(task_id)
    if entry is None:
        with _bg_lock:
            known = sorted(_bg_tasks) or ["(kosong)"]
        return f"Error: task '{task_id}' tidak ditemukan. Task tersedia: {', '.join(known)}"
    if entry["status"] != "running":
        return f"[{task_id}] sudah selesai (status={entry['status']}, exit={entry['returncode']})."
    entry["killed"] = True
    try:
        entry["proc"].kill()
    except Exception:
        pass
    thread = entry.get("thread")
    if thread:
        thread.join(timeout=2)
    return f"[{task_id}] dihentikan (output tersimpan di {entry['log']})."


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
    if not request_approval("git_publish", summarize_action("git_publish", {"message": message})):
        return "DITOLAK PENGGUNA: publish tidak disetujui. Jangan coba lagi tanpa instruksi baru."
    _checkpoint_before("git_publish", summarize_action("git_publish", {"message": message}))

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


def delegate_to_brachio(task: str, focus: str = "", context: str = "") -> str:
    """Delegasikan tugas analisis (code review, logika, kualitas) ke sub-agent Brachio. Berjalan dalam mode Plan (read-only)."""
    from rex.subagents import get_subagent
    agent = get_subagent("brachio")
    if agent is None:
        return "Error: sub-agent brachio tidak tersedia."
    full_task = f"{task}\n\nFocus: {focus}" if focus else task
    return agent.run(full_task, context)


def delegate_to_raptor(task: str, context: str = "") -> str:
    """Delegasikan tugas bug hunting & analisis traceback ke sub-agent Raptor. Berjalan dalam mode Plan (read-only)."""
    from rex.subagents import get_subagent
    agent = get_subagent("raptor")
    if agent is None:
        return "Error: sub-agent raptor tidak tersedia."
    return agent.run(task, context)


def delegate_to_trike(task: str, context: str = "") -> str:
    """Delegasikan audit keamanan (vulnerabilitas, secret leak, injection) ke sub-agent Trike. Berjalan dalam mode Plan (read-only)."""
    from rex.subagents import get_subagent
    agent = get_subagent("trike")
    if agent is None:
        return "Error: sub-agent trike tidak tersedia."
    return agent.run(task, context)


def delegate_to_ptero(task: str, context: str = "") -> str:
    """Delegasikan analisis arsitektur & dokumentasi teknis ke sub-agent Ptero. Berjalan dalam mode Plan (read-only)."""
    from rex.subagents import get_subagent
    agent = get_subagent("ptero")
    if agent is None:
        return "Error: sub-agent ptero tidak tersedia."
    return agent.run(task, context)


def delegate_to_dilo(task: str, context: str = "") -> str:
    """Delegasikan audit kualitas & anti-slop (boilerplate, buzzword, maintainability) ke sub-agent Dilo. Berjalan dalam mode Plan (read-only)."""
    from rex.subagents import get_subagent
    agent = get_subagent("dilo")
    if agent is None:
        return "Error: sub-agent dilo tidak tersedia."
    return agent.run(task, context)


def apply_patch(patch: str) -> str:
    """
    Terapkan unified diff ke file workspace (Hanya aktif di Mode Build).

    Format: unified diff standar (git diff / diff -u) — header ---/+++,
    hunks @@ ... @@, baris konteks ' ', tambahan '+', hapus '-'. Satu patch
    boleh memuat banyak file. Penerapannya fuzzy (context match dengan
    window terbatas) seperti patch(1); hunk yang tidak cocok membatalkan
    seluruh patch TANPA menulis apa pun.
    """
    mode = get_active_mode()
    if mode == "plan":
        return "TIDAK DIIZINKAN: apply_patch hanya aktif di Mode Build."

    try:
        entries = _diffs.parse_diff(patch)
    except _diffs.DiffError as e:
        return f"Error patch: {e}"

    summary_bits = []
    for entry in entries:
        old, new = _diffs._normalized_file_paths(entry)
        target_name = new or old
        action = "delete" if _diffs.deleted_file(entry) else ("create" if _diffs.created_file(entry) else "edit")
        summary_bits.append(f"{action} {target_name} ({len(entry['hunks'])} hunk)")
    summary = "; ".join(summary_bits)

    if not request_approval("edit_file", f"apply_patch: {summary}"):
        return "DITOLAK PENGGUNA: patch tidak disetujui. Jangan coba lagi tanpa instruksi baru."

    # Compute every file's new content FIRST; only write when all hunks match.
    planned: List[tuple] = []
    for entry in entries:
        old, new = _diffs._normalized_file_paths(entry)
        if _diffs.deleted_file(entry):
            target = _target(old)
            if _is_sensitive(target) or not target or not target.exists():
                return f"DIBLOKIR KEAMANAN: tidak bisa menghapus '{old}'."
            planned.append((target, "delete", None))
        elif _diffs.created_file(entry):
            target = _target(new)
            if _is_sensitive(target) or not target:
                return f"DIBLOKIR KEAMANAN: path '{new}' tidak diizinkan."
            planned.append((target, "create", _diffs.build_new_file(entry["hunks"])))
        else:
            target = _target(new or old)
            if _is_sensitive(target) or not target or not target.exists():
                return f"Error: file '{new or old}' tidak ditemukan / tidak diizinkan."
            try:
                with open(target, "r", encoding="utf-8") as f:
                    current = f.read()
                updated = _diffs.apply_to_text(current, entry["hunks"])
            except _diffs.DiffError as e:
                return f"Error patch pada '{new or old}': {e} — tidak ada file yang diubah."
            except OSError as e:
                return f"Error saat membaca '{new or old}': {e}"
            planned.append((target, "edit", updated))

    # All hunks validated — snapshot once, then write everything.
    _checkpoint_before("apply_patch", f"apply_patch: {summary}")
    applied = []
    for target, action, content in planned:
        try:
            if action == "delete":
                target.unlink()
                applied.append(f"hapus {target.name}")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with open(target, "w", encoding="utf-8") as f:
                    f.write(content)
                applied.append(f"{action} {target.name}")
        except OSError as e:
            return f"Berhenti di tengah: {applied} — gagal menulis {target.name}: {e}"
    return "Patch diterapkan: " + ", ".join(applied)


def todo_write(todos: list) -> str:
    """
    Ganti isi todo list sesi (agent task board).

    Seluruh daftar dikirim setiap kali (bukan diff) — pola TodoWrite yang
    lazim: model menulis ulang board lengkap dengan status terkini.
    Aman di kedua mode (tidak menyentuh file proyek); hasil dikembalikan
    sebagai konfirmasi teks untuk model. Board juga dipantau UI lewat
    StepEvent ``todo_update`` dari rex.core.
    """
    raw_count = len(todos) if isinstance(todos, list) else 0
    board = _todos.write(_todos.current_session(), todos)
    if raw_count == 0:
        return "Todo list dikosongkan."
    note = "" if len(board) == raw_count else " (beberapa item tidak valid diabaikan)"
    return (
        f"Todo list diperbarui — {_todos.summary(board)}{note}:\n"
        f"{_todos.format_board(board)}"
    )


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
        "name": "run_command_bg",
        "description": "Memulai perintah jangka panjang di background (dev server, build, test suite) tanpa memblokir percakapan (Hanya Mode Build).",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Perintah yang dijalankan di background"}
            },
            "required": ["command"]
        }
    },
    {
        "name": "task_output",
        "description": "Membaca output terbaru task background; opsional menunggu beberapa detik sampai selesai. Aktif di PLAN & BUILD.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "ID task dari run_command_bg (misal: bg_a1b2c3)"},
                "wait_seconds": {"type": "integer", "description": "Tunggu maksimal (0-30 detik) sampai task selesai"}
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "task_kill",
        "description": "Menghentikan task background yang masih berjalan (Hanya Mode Build).",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "ID task yang akan dihentikan"}
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "web_search",
        "description": "Mencari di web via DuckDuckGo dan mengembalikan judul/link/snippet. Aktif di PLAN & BUILD.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Kata kunci pencarian"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "web_fetch",
        "description": "Mengambil isi satu halaman web sebagai teks (domain publik; kena allowlist config web.allowed_domains bila diisi). Aktif di PLAN & BUILD.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL http/https yang akan diambil"}
            },
            "required": ["url"]
        }
    },
    {
        "name": "load_skill",
        "description": "Memuat instruksi lengkap sebuah skill on-demand (daftar skill ada di system prompt). Aktif di PLAN & BUILD.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nama skill (misal: release-checklist)"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "delegate_parallel",
        "description": "Menjalankan beberapa sub-agent spesialis secara paralel, masing-masing di worktree git terpisah (tulisannya terisolasi). Butuh repo git; patch hasilnya direview lalu diterapkan via apply_patch.",
        "parameters": {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "description": "Maksimal 3 tugas",
                    "items": {
                        "type": "object",
                        "properties": {
                            "agent": {"type": "string", "description": "brachio|raptor|trike|ptero|dilo"},
                            "task": {"type": "string", "description": "Tugas untuk sub-agent"}
                        },
                        "required": ["agent", "task"]
                    }
                }
            },
            "required": ["tasks"]
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
    },
    {
        "name": "delegate_to_brachio",
        "description": "Delegasikan analisis kode & logika umum (read-only, mode Plan) ke sub-agent Brachio.",
        "parameters": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Tugas analisis yang akan dijalankan Brachio"},
                "focus": {"type": "string", "description": "Fokus spesifik analisa (misal: 'performance', 'security review')"},
                "context": {"type": "string", "description": "Konteks tambahan"}
            },
            "required": ["task"]
        }
    },
    {
        "name": "delegate_to_raptor",
        "description": "Delegasikan bug hunting & analisis traceback (read-only, mode Plan) ke sub-agent Raptor.",
        "parameters": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Tugas bug hunting / traceback analysis"},
                "context": {"type": "string", "description": "Konteks tambahan (log error, stack trace)"}
            },
            "required": ["task"]
        }
    },
    {
        "name": "delegate_to_trike",
        "description": "Delegasikan audit keamanan / vulnerability scanning (read-only, mode Plan) ke sub-agent Trike.",
        "parameters": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Tugas audit keamanan"},
                "context": {"type": "string", "description": "Konteks tambahan"}
            },
            "required": ["task"]
        }
    },
    {
        "name": "delegate_to_ptero",
        "description": "Delegasikan analisis arsitektur & dokumentasi teknis (read-only, mode Plan) ke sub-agent Ptero.",
        "parameters": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Tugas analisis arsitektur/dokumentasi"},
                "context": {"type": "string", "description": "Konteks tambahan"}
            },
            "required": ["task"]
        }
    },
    {
        "name": "delegate_to_dilo",
        "description": "Delegasikan audit kualitas & anti-slop (read-only, mode Plan) ke sub-agent Dilo.",
        "parameters": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Tugas audit kualitas/anti-slop"},
                "context": {"type": "string", "description": "Konteks tambahan"}
            },
            "required": ["task"]
        }
    },
    {
        "name": "apply_patch",
        "description": ("Terapkan unified diff (git diff / diff -u) ke file workspace. "
                        "Lebih presisi daripada edit_file untuk perubahan multi-baris/multi-file. "
                        "Hanya aktif di Mode Build; hunk yang tidak cocok membatalkan seluruh patch."),
        "parameters": {
            "type": "object",
            "properties": {
                "patch": {"type": "string", "description": "Unified diff lengkap (---/+++, @@ hunks, +/-/spasi)"}
            },
            "required": ["patch"]
        }
    },
    {
        "name": "todo_write",
        "description": ("Perbarui todo list tugas sesi ini. Kirim SELURU daftar setiap kali "
                        "(bukan diff): [{content, status}] dengan status pending/in_progress/completed. "
                        "Gunakan untuk merencanakan langkah sebelum eksekusi dan menandai progres."),
        "parameters": {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "Daftar lengkap todo terkini",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string", "description": "Uraian tugas (singkat)"},
                            "status": {"type": "string", "enum": ["pending", "in_progress", "completed"], "description": "Status tugas"}
                        },
                        "required": ["content", "status"]
                    }
                }
            },
            "required": ["todos"]
        }
    }
]


def load_skill(name: str) -> str:
    """Muat isi skill on-demand dari .rex/skills/<name>/SKILL.md (PLAN & BUILD)."""
    from rex.skills import get_skill
    skill = get_skill(str(name or "").strip())
    if skill is None:
        return f"Error: skill '{name}' tidak ditemukan. Lihat daftar skill di system prompt (section Skills)."
    return f"Skill '{skill['name']}' — {skill['description']}\n\n{skill['body']}"


def delegate_parallel(tasks: List[dict]) -> str:
    """Jalankan beberapa sub-agent paralel dalam worktree terpisah (butuh git)."""
    from rex.subagents import run_worktree_delegates
    if not isinstance(tasks, list) or not tasks:
        return "Error: tasks harus list berisi {agent, task}."
    results = run_worktree_delegates(tasks)
    lines = []
    for item in results:
        lines.append(f"━━ {item.get('agent', '?')} " + "─" * 40)
        if item.get("error"):
            lines.append(f"[GAGAL] {item['error']}")
        if item.get("response"):
            lines.append(f"Hasil: {item['response']}")
        if item.get("diff"):
            lines.append(f"Patch tersedia ({len(item['diff'])} chars) — tinjau lalu terapkan dengan apply_patch bila sesuai.")
        lines.append("")
    return "\n".join(lines).strip()


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
    "delegate_to_brachio": delegate_to_brachio,
    "delegate_to_raptor": delegate_to_raptor,
    "delegate_to_trike": delegate_to_trike,
    "delegate_to_ptero": delegate_to_ptero,
    "delegate_to_dilo": delegate_to_dilo,
    "todo_write": todo_write,
    "apply_patch": apply_patch,
    "run_command_bg": run_command_bg,
    "task_output": task_output,
    "task_kill": task_kill,
    "web_search": web_search,
    "web_fetch": web_fetch,
    "load_skill": load_skill,
    "delegate_parallel": delegate_parallel,
}
