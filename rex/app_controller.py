"""
rex.app_controller
==================
One brain shared by every Rex frontend — Desktop web UI, TUI, and CLI.

``ChatController`` owns:

- the agent + session lifecycle (crash-recovery resume, /new, /resume, /use)
- the agent run thread (worker thread + marshalled callbacks — the pattern
  proven in the TUI)
- the *merged* slash-command dispatch (the union of the old TUI and CLI
  chains — one place, no duplicates)
- commit proposal state

It emits framework-neutral event dicts, never Rich markup. Every frontend
renders the same events its own way:

    {"type": "message", "text": ..., "style": "info|success|error|dim|warn"}
    {"type": "table", "title": ..., "text": ...}          # preformatted output
    {"type": "stream_delta"|"thought"|"tool_call"|"tool_result"|"todo_update"|"usage_alert", ...}
    {"type": "mode_changed", "mode": "PLAN"|"BUILD"}
    {"type": "session_changed", "session_id": ..., "title": ...}
    {"type": "providers", "active": ..., "items": [...]}   # /models data
    {"type": "settings", "data": {...}}                    # /settings data
    {"type": "help", "items": [...]}
    {"type": "agent_state", "running": true|false}
    {"type": "submit_prompt", "text": ...}                 # /skill → run this
    {"type": "quit"}

Frontend-specific concerns (theme, command palette, voice capture, the
actual widgets) stay in the frontend.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional

from rex.config import (
    WORKSPACE_DIR,
    get_active_mode,
    get_active_provider_info,
    load_config,
    normalize_config,
    save_config,
    set_active_mode,
)
from rex.core import RexAgent, StepEvent
from rex.logging_setup import log
from rex.sessions import session_store

Event = Dict[str, Any]


def msg(text: str, style: str = "info") -> Event:
    return {"type": "message", "text": text, "style": style}


def table(title: str, text: str) -> Event:
    return {"type": "table", "title": title, "text": text}


class ChatController:
    """Shared session/agent/command brain for every Rex frontend."""

    def __init__(self, session_id: Optional[str] = None, auto_resume: bool = True):
        self._store = session_store  # injectable: tests patch rex.app_controller.session_store
        self.agent: Optional[RexAgent] = None
        self.session_id: Optional[str] = None
        self._running = False
        self._state_lock = threading.Lock()
        self._pending_commit: Optional[str] = None
        resumed_note: Optional[str] = None

        if session_id:
            self.session_id = session_id
        else:
            resumed = None
            if auto_resume:
                try:
                    resumed = self._store.last_open_session()
                except Exception:
                    resumed = None
            if resumed:
                self.session_id = resumed["id"]
                resumed_note = (
                    f"Sesi sebelumnya dilanjutkan: {(resumed.get('title') or '')[:50]} "
                    f"({resumed.get('message_count', 0)} pesan)"
                )
            else:
                self._create_session()
        self._build_agent()
        if resumed_note:
            # surfaced on the first events pull (frontends call initial_events())
            self._resumed_note = resumed_note

    # ── session lifecycle ─────────────────────────────────────────────
    def _create_session(self) -> None:
        pid, _, model = get_active_provider_info()
        self.session_id = self._store.create(pid, model)["id"]

    def _build_agent(self) -> bool:
        try:
            self.agent = RexAgent(self.session_id)
            return True
        except Exception as exc:
            self.agent = None
            log.error("controller agent init failed: %s", exc)
            return False

    def agent_ready(self) -> bool:
        return self.agent is not None

    def new_session(self) -> Event:
        if self.session_id:
            try:
                self._store.close(self.session_id)
            except Exception:
                pass
        self._create_session()
        ok = self._build_agent()
        return {
            "type": "session_changed",
            "session_id": self.session_id,
            "title": "Percakapan baru",
            "agent_ok": ok,
        }

    def resume_session(self, session_id: str) -> Event:
        try:
            data = self._store.load(session_id)
        except (FileNotFoundError, ValueError):
            return msg(f"Session ID '{session_id}' tidak ditemukan.", "error")
        self.session_id = session_id
        ok = self._build_agent()
        return {
            "type": "session_changed",
            "session_id": session_id,
            "title": data.get("title") or "Percakapan baru",
            "message_count": len(data.get("messages") or []),
            "agent_ok": ok,
        }

    def delete_session(self, session_id: str) -> Event:
        try:
            self._store.delete(session_id)
        except (FileNotFoundError, ValueError):
            return msg(f"Session ID '{session_id}' tidak ditemukan.", "error")
        if session_id == self.session_id:
            self.new_session()
            return msg("Sesi dihapus — sesi baru dimulai.", "success")
        return msg("Sesi dihapus.", "success")

    def list_sessions(self) -> Event:
        return table("Sesi tersimpan", self._sessions_text())

    def _sessions_text(self) -> str:
        lines = []
        for i, item in enumerate(self._store.list()[:12], 1):
            marker = "*" if item["id"] == self.session_id else " "
            count = 0
            try:
                count = len(self._store.load(item["id"]).get("messages", []))
            except Exception:
                pass
            lines.append(
                f"{marker} {i}. {(item.get('title') or '')[:44]}  "
                f"[{item.get('model') or '?'} · {count} pesan · {item['id'][:8]}]"
            )
        return "\n".join(lines) or "(belum ada sesi)"

    # ── agent run ─────────────────────────────────────────────────────
    def is_running(self) -> bool:
        return self._running

    def abort(self) -> None:
        if self.agent:
            self.agent.abort()

    def submit(self, text: str, emit: Callable[[Event], None]) -> None:
        """
        Main entry from any frontend. Slash commands are dispatched
        synchronously (their events emitted immediately); plain text runs
        the agent on a worker thread with events streamed to ``emit``.
        """
        text = (text or "").strip()
        if not text:
            return
        if text.startswith("/"):
            for event in self.dispatch(text):
                emit(event)
            return
        self._run_agent_thread(text, emit)

    def initial_events(self) -> List[Event]:
        """Startup events for a freshly attached frontend."""
        events: List[Event] = []
        note = getattr(self, "_resumed_note", None)
        if note:
            events.append(msg(note, "warn"))
            self._resumed_note = None
        return events

    def _run_agent_thread(self, text: str, emit: Callable[[Event], None]) -> None:
        with self._state_lock:
            if self._running:
                emit(msg("Agen masih memproses — tunggu, atau Ctrl+C untuk abort.", "warn"))
                return
            if self.agent is None:
                emit(msg("Provider belum siap. Buka Settings dan isi API key.", "error"))
                return
            self._running = True
        emit({"type": "agent_state", "running": True})

        def emit_safe(event: Event) -> None:
            try:
                emit(event)
            except Exception:
                pass  # a dead frontend must not kill the run

        def step_to_event(step: StepEvent) -> Event:
            data = step.data
            if step.event_type == "tool_call":
                return {"type": "tool_call", "name": data.get("name"), "args": data.get("args")}
            if step.event_type == "tool_result":
                return {"type": "tool_result", "name": data.get("name"), "result": data.get("result")}
            if step.event_type == "stream_delta":
                return {"type": "stream_delta", "text": str(data)}
            if step.event_type in ("thought", "todo_update", "usage_alert"):
                return {"type": step.event_type, "data": data}
            return {"type": "message", "text": str(data), "style": "dim"}

        def worker() -> None:
            try:
                result = self.agent.run(text, on_step=lambda s: emit_safe(step_to_event(s)))
                emit_safe({"type": "done", "text": result})
            except Exception as exc:
                emit_safe(msg(f"Error: {type(exc).__name__}: {str(exc)[:300]}", "error"))
            finally:
                with self._state_lock:
                    self._running = False
                emit_safe({"type": "agent_state", "running": False})

        threading.Thread(target=worker, daemon=True).start()

    # ── slash-command dispatch (merged TUI + CLI) ─────────────────────
    def dispatch(self, text: str) -> List[Event]:
        """Handle one ``/command`` line; returns the resulting events."""
        parts = text.split()
        cmd = parts[0].lower()
        args = text[len(parts[0]):].strip()
        handler = self._HANDLERS.get(cmd)
        if handler is None:
            return [msg(f"Perintah tidak dikenal: {cmd} — /help untuk daftar.", "error")]
        try:
            return handler(self, args)
        except Exception as exc:
            log.error("command %s failed: %s", cmd, exc)
            return [msg(f"Error menjalankan {cmd}: {type(exc).__name__}: {str(exc)[:200]}", "error")]

    # ── individual commands ───────────────────────────────────────────
    def _cmd_help(self, args: str) -> List[Event]:
        items = [
            ("/plan", "Mode PLAN (read-only)"),
            ("/build", "Mode BUILD (otonomous)"),
            ("/models", "Provider & model — data + pindah aktif"),
            ("/settings", "Ringkasan pengaturan yang bisa diubah"),
            ("/cost", "Pemakaian token & biaya sesi"),
            ("/init", "Buat REX.md instruksi proyek"),
            ("/commit [yes|no]", "Usul pesan commit AI, lalu konfirmasi"),
            ("/pr", "Deskripsi PR dari diff nyata"),
            ("/ask <query>", "Cari simbol via indeks kode"),
            ("/imports", "Graf import antar-modul"),
            ("/stats", "Statistik token & biaya antar sesi"),
            ("/diff", "Review perubahan sesi"),
            ("/doctor", "Cek kesehatan instalasi"),
            ("/status", "Status seluruh subsistem"),
            ("/test", "Jalankan test_hook proyek"),
            ("/checkpoints", "Daftar snapshot otomatis"),
            ("/rewind <n>", "Kembalikan workspace n checkpoint"),
            ("/undo /redo", "Rollback satu langkah / ulangi"),
            ("/sessions", "Daftar sesi tersimpan"),
            ("/resume <n>", "Lanjutkan sesi lama"),
            ("/new", "Sesi baru"),
            ("/use <id>", "Pakai sesi tertentu"),
            ("/delete <id>", "Hapus sesi"),
            ("/export [md|html]", "Ekspor sesi ke file"),
            ("/skills", "Daftar skill on-demand"),
            ("/skill <name>", "Jalankan skill"),
            ("/compare <q>", "Bandingkan jawaban antar provider"),
            ("/plugins", "Tabel plugin terpasang"),
            ("/scheduler", "Daftar job cron"),
            ("/files", "Daftar file workspace"),
            ("/anti-slop <text>", "Audit & bersihkan klise AI"),
            ("/n8n", "Template workflow n8n"),
            ("/help", "Bantuan ini"),
            ("/exit", "Keluar"),
        ]
        return [{"type": "help", "items": items}]

    def _cmd_plan(self, args: str) -> List[Event]:
        set_active_mode("plan")
        return [{"type": "mode_changed", "mode": "PLAN"}, msg("Mode PLAN — analisis read-only.", "info")]

    def _cmd_build(self, args: str) -> List[Event]:
        set_active_mode("build")
        return [{"type": "mode_changed", "mode": "BUILD"}, msg("Mode BUILD — eksekusi otonom.", "success")]

    def _cmd_models(self, args: str) -> List[Event]:
        import os

        from rex.config import ENV_FILE
        cfg = normalize_config(load_config())
        env_keys = _env_keys(ENV_FILE)
        items = []
        for pid, prov in cfg.get("providers", {}).items():
            key_env = str(prov.get("api_key_env", ""))
            has_key = bool(os.getenv(key_env, "")) or (key_env in env_keys)
            items.append({
                "id": pid,
                "name": prov.get("name", pid),
                "model": prov.get("model", "?"),
                "available_models": prov.get("available_models", []),
                "api_key_env": key_env,
                "has_key": has_key,
                "active": pid == cfg.get("active_provider"),
            })
        if not args:
            return [{"type": "providers", "active": cfg.get("active_provider"), "items": items}]
        parts = args.split(None, 1)
        pid = parts[0]
        if pid not in cfg.get("providers", {}):
            return [msg(f"Provider '{pid}' tidak dikenal.", "error")]
        prov = cfg["providers"][pid]
        model = parts[1].strip() if len(parts) > 1 else prov.get("model")
        if model not in prov.get("available_models", [model]):
            return [msg(f"Model '{model}' tidak ada di {prov.get('available_models', [])}.", "error")]
        cfg["active_provider"] = pid
        cfg["active_model"] = model
        cfg["providers"][pid]["model"] = model
        save_config(cfg)
        return [
            msg(f"Provider aktif: {pid} · model: {model} — berlaku di pesan berikutnya.", "success"),
            {"type": "providers", "active": pid, "items": items},
        ]

    def _cmd_settings(self, args: str) -> List[Event]:
        cfg = normalize_config(load_config())
        pid, prov, model = get_active_provider_info()
        data = {
            "active_provider": pid,
            "active_model": model,
            "active_mode": cfg.get("active_mode"),
            "token_budget": cfg.get("token_budget", 0),
            "max_steps": cfg.get("max_steps", 25),
            "stream_enabled": cfg.get("stream_enabled", True),
            "anti_slop_enabled": cfg.get("anti_slop_enabled", True),
            "approval": cfg.get("approval", {}),
            "updates": cfg.get("updates", {}),
            "providers": [
                {"id": p, "name": v.get("name", p), "model": v.get("model"), "api_key_env": v.get("api_key_env")}
                for p, v in cfg.get("providers", {}).items()
            ],
        }
        return [{"type": "settings", "data": data}]

    def _cmd_cost(self, args: str) -> List[Event]:
        summary = self.agent.usage.format_summary() if self.agent else "(agen belum siap)"
        return [msg(f"Pemakaian sesi — {summary}", "info")]

    def _cmd_init(self, args: str) -> List[Event]:
        from rex.context_inject import create_rex_md
        created, path = create_rex_md()
        if created:
            return [msg(f"REX.md dibuat di {path}", "success")]
        return [msg(f"REX.md sudah ada di {path} — tidak diubah.", "warn")]

    def _cmd_commit(self, args: str) -> List[Event]:
        rest = args.strip().lower()
        if rest == "no":
            self._pending_commit = None
            return [msg("Usulan commit dibatalkan.", "dim")]
        if rest == "yes" and self._pending_commit:
            from rex.autogit import commit_with_message
            result = commit_with_message(self._pending_commit, confirm=lambda m: True)
            self._pending_commit = None
            return [msg(result, "success")]
        if self._pending_commit:
            return [msg(f"Menunggu konfirmasi: {self._pending_commit} — /commit yes atau /commit no", "warn")]
        from rex.autogit import generate_commit_message
        message = generate_commit_message()
        if not message:
            return [msg("Tidak ada perubahan untuk di-commit (atau provider gagal).", "warn")]
        self._pending_commit = message
        return [msg(f"Usulan commit: {message} — konfirmasi dengan /commit yes (batal: /commit no)", "info")]

    def _cmd_pr(self, args: str) -> List[Event]:
        from rex.autogit import generate_pr_description
        description = generate_pr_description()
        if not description:
            return [msg("Tidak ada perubahan untuk dideskripsikan (atau provider gagal).", "warn")]
        return [msg(f"Deskripsi PR usulan:\n{description}", "info")]

    def _generic_table(self, args: str, importer: str, func: str, title: str) -> List[Event]:
        module = __import__(importer, fromlist=[func])
        return [table(title, getattr(module, func)())]

    def _cmd_ask(self, args: str) -> List[Event]:
        from rex.codeindex import build_index, format_ask
        if not args:
            return [msg("Pakai: /ask <nama simbol/file/topik>", "dim")]
        return [table(f"/ask {args}", format_ask(build_index(), args))]

    def _cmd_test(self, args: str) -> List[Event]:
        from rex.review import run_tests_hook
        result = run_tests_hook()
        if not result.get("ran"):
            return [msg("test_hook belum diset — isi config test_hook.command + enabled: true.", "warn")]
        if result.get("passed"):
            return [msg("Test lulus ✓", "success")]
        return [msg(f"Test gagal ✘ — hasil:\n{str(result.get('output', ''))[-2000:]}", "error")]

    def _cmd_rewind(self, args: str) -> List[Event]:
        from rex.checkpoints import format_timeline, rewind
        if not args.isdigit():
            return [table("Timeline checkpoint", format_timeline())]
        result = rewind(int(args))
        if result:
            return [msg(f"Workspace dikembalikan {result['steps']} checkpoint ke {result['restored'][:9]} — /redo membatalkan.", "success")]
        return [msg("Tidak bisa rewind (riwayat kurang / tidak ada checkpoint).", "warn")]

    def _cmd_undo(self, args: str) -> List[Event]:
        from rex.checkpoints import undo
        result = undo()
        if result:
            return [msg(f"Workspace dikembalikan ke {result['previous'][:9]} — /redo membatalkan.", "success")]
        return [msg("Tidak ada yang bisa di-undo.", "warn")]

    def _cmd_redo(self, args: str) -> List[Event]:
        from rex.checkpoints import redo
        result = redo()
        if result:
            return [msg(f"Keadaan sebelum undo dipulihkan ({result['restored'][:9]}).", "success")]
        return [msg("Tidak ada yang bisa di-redo.", "warn")]

    def _cmd_sessions(self, args: str) -> List[Event]:
        return [self.list_sessions()]

    def _cmd_resume(self, args: str) -> List[Event]:
        sessions = self._store.list()[:8]
        if not sessions:
            return [msg("Belum ada sesi tersimpan.", "warn")]
        if not args.isdigit():
            lines = [f"{i}. {(m.get('title') or '')[:44]} [{m.get('model') or '?'}]" for i, m in enumerate(sessions, 1)]
            return [table("Sesi terakhir — /resume <n>", "\n".join(lines))]
        idx = int(args)
        if not (1 <= idx <= len(sessions)):
            return [msg(f"Nomor di luar rentang 1-{len(sessions)}.", "error")]
        event = self.resume_session(sessions[idx - 1]["id"])
        return [event, msg(f"Lanjut sesi: {(event.get('title') or '')[:50]}", "success")]

    def _cmd_use(self, args: str) -> List[Event]:
        if not args:
            return [msg("Pakai: /use <session-id>", "dim")]
        return [self.resume_session(args.strip())]

    def _cmd_delete(self, args: str) -> List[Event]:
        if not args:
            return [msg("Pakai: /delete <session-id>", "dim")]
        return [self.delete_session(args.strip())]

    def _cmd_export(self, args: str) -> List[Event]:
        from rex.export import export_session
        if not self.session_id:
            return [msg("Belum ada sesi aktif untuk diekspor.", "warn")]
        return [msg(export_session(self.session_id, fmt=args or "md"), "info")]

    def _cmd_skills(self, args: str) -> List[Event]:
        from rex.skills import load_skills
        skills = load_skills()
        if not skills:
            return [msg("Belum ada skill (.rex/skills/<name>/SKILL.md).", "warn")]
        lines = [f"{s['name']} — {s['description']}" for s in skills.values()]
        return [table("Skills — jalankan dengan /skill <name>", "\n".join(lines))]

    def _cmd_skill(self, args: str) -> List[Event]:
        from rex.skills import get_skill, load_skills
        parts = args.split(None, 1)
        name = parts[0] if parts else ""
        extra = parts[1].strip() if len(parts) > 1 else ""
        skill = get_skill(name) if name else None
        if skill is None:
            events = [msg("Pakai: /skill <name> [args] — daftar:", "dim")]
            events.extend(self._cmd_skills(""))
            return events
        prompt = skill["body"] + (f"\n\nArgumen: {extra}" if extra else "")
        return [{"type": "submit_prompt", "text": prompt}]

    def _cmd_compare(self, args: str) -> List[Event]:
        from rex.core import compare_models
        if not args:
            return [msg("Pakai: /compare <pertanyaan>", "dim")]
        results = compare_models(args)
        lines = []
        for item in results:
            label = f"{item['provider']} · {item['model']} ({item['elapsed']}s)"
            body = f"[GAGAL] {item['error']}" if item.get("error") else str(item.get("answer") or "(kosong)")[:1500]
            lines.append(f"━━ {label}\n{body}")
        return [table("/compare", "\n\n".join(lines))]

    def _cmd_files(self, args: str) -> List[Event]:
        try:
            files = sorted(p.relative_to(WORKSPACE_DIR).as_posix() for p in WORKSPACE_DIR.rglob("*") if p.is_file())
        except OSError:
            files = []
        return [table("File workspace", "\n".join(files[:200]) or "(workspace kosong)")]

    def _cmd_anti_slop(self, args: str) -> List[Event]:
        from rex.anti_slop import clean_slop
        if not args:
            return [msg("Pakai: /anti-slop <teks yang diaudit>", "dim")]
        cleaned, notes = clean_slop(args)
        detail = f"\nCatatan: {notes}" if notes else ""
        return [msg(f"Hasil bersih:\n{cleaned}{detail}", "info")]

    def _cmd_n8n(self, args: str) -> List[Event]:
        from rex.automation.n8n_builder import create_webhook_ai_workflow
        wf_path = create_webhook_ai_workflow(name="Otomasi_Baru")
        return [msg(f"Template workflow n8n dibuat: {wf_path} — import ke dashboard n8n.", "success")]

    def _cmd_scheduler(self, args: str) -> List[Event]:
        from rex.scheduler import get_scheduler
        jobs = get_scheduler().get_job_status()
        if not jobs:
            return [msg("Tidak ada job terdaftar.", "dim")]
        lines = [
            f"{j.get('id', '?')}  [{j.get('cron', '?')}]  mode={j.get('mode', '?')}  "
            f"enabled={j.get('enabled', '?')}  last={j.get('last_run') or '-'}"
            for j in jobs
        ]
        return [table("Scheduler jobs", "\n".join(lines))]

    def _cmd_todos(self, args: str) -> List[Event]:
        from rex.todos import format_board, get, summary
        board = get(self.session_id)
        return [table(f"Todos [{summary(board)}]", format_board(board))]

    def _cmd_exit(self, args: str) -> List[Event]:
        return [{"type": "quit"}]

    _HANDLERS: Dict[str, Callable[["ChatController", str], List[Event]]] = {
        "/help": _cmd_help,
        "/plan": _cmd_plan,
        "/build": _cmd_build,
        "/models": _cmd_models,
        "/provider": _cmd_models,
        "/settings": _cmd_settings,
        "/cost": _cmd_cost,
        "/init": _cmd_init,
        "/commit": _cmd_commit,
        "/pr": _cmd_pr,
        "/ask": _cmd_ask,
        "/imports": lambda self, args: ChatController._generic_table(
            self, args, "rex.codeindex", "format_import_graph", "Graf import"
        ),
        "/stats": lambda self, args: ChatController._generic_table(self, args, "rex.stats", "format_stats", "Statistik"),
        "/diff": lambda self, args: ChatController._generic_table(self, args, "rex.review", "format_session_diff", "Diff sesi"),
        "/doctor": lambda self, args: ChatController._generic_table(self, args, "rex.review", "format_doctor", "Doctor"),
        "/status": lambda self, args: ChatController._generic_table(self, args, "rex.status", "format_status", "Status"),
        "/plugins": lambda self, args: ChatController._generic_table(self, args, "rex.plugins", "format_plugins_table", "Plugins"),
        "/checkpoints": lambda self, args: ChatController._generic_table(self, args, "rex.checkpoints", "format_checkpoints_table", "Checkpoints"),
        "/todos": _cmd_todos,
        "/test": _cmd_test,
        "/rewind": _cmd_rewind,
        "/undo": _cmd_undo,
        "/redo": _cmd_redo,
        "/sessions": _cmd_sessions,
        "/resume": _cmd_resume,
        "/new": lambda self, args: [self.new_session()],
        "/reset": lambda self, args: [self.new_session()],
        "/use": _cmd_use,
        "/delete": _cmd_delete,
        "/export": _cmd_export,
        "/skills": _cmd_skills,
        "/skill": _cmd_skill,
        "/compare": _cmd_compare,
        "/files": _cmd_files,
        "/anti-slop": _cmd_anti_slop,
        "/n8n": _cmd_n8n,
        "/scheduler": _cmd_scheduler,
        "/exit": _cmd_exit,
        "/quit": _cmd_exit,
    }


def _env_keys(env_file) -> Dict[str, str]:
    """Parse KEY=VALUE pairs from a .env file (missing file -> {})."""
    try:
        result: Dict[str, str] = {}
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip().strip("'\"")
        return result
    except OSError:
        return {}
