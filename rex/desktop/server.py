"""
rex.desktop.server
==================
Local UI host for Rex Desktop — the native-app front end.

- stdlib only (ThreadingHTTPServer), bound to **127.0.0.1** on a free
  port, guarded by a per-launch random token (``?t=...``) so nothing on
  the network can drive the agent.
- ``GET /``            the SPA (static/index.html + app.js + app.css)
- ``GET /api/events``  SSE stream of controller events (stream deltas,
  tool calls/results, mode changes, approval requests, agent state)
- ``POST /api/send``   submit a message / slash command
- ``POST /api/abort``  cooperative abort of the running round
- ``GET  /api/state``  snapshot: session, mode, model, provider, running
- ``POST /api/mode``   switch PLAN/BUILD
- ``GET  /api/sessions`` + ``POST /api/sessions`` {action, id}
- Approval gate: the controller-side provider renders an
  ``approval_request`` event; ``POST /api/approve`` {decision, remember}
  resolves it.
"""

from __future__ import annotations

import json
import queue
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Dict, List, Optional

from rex.app_controller import ChatController, Event
from rex.approval import set_provider, reset_session_allows
from rex.config import get_active_mode, get_active_provider_info, set_active_mode
from rex.logging_setup import log

STATIC_DIR = Path(__file__).resolve().parent / "static"
QUEUE_TIMEOUT = 0.5
SSE_PING_SEC = 15


class DesktopHub:
    """Fan-out event bus + approval bridge between HTTP and the controller."""

    def __init__(self, controller: ChatController):
        self.controller = controller
        self._subscribers: List[queue.Queue] = []
        self._lock = threading.Lock()
        self._approval_waiters: Dict[str, dict] = {}
        self._counter = 0
        self.startup_events: List[Event] = list(controller.initial_events())

    # ── event fan-out ─────────────────────────────────────────────────
    def subscribe(self) -> queue.Queue:
        outbox: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.append(outbox)
            for event in self.startup_events:
                outbox.put(event)
        return outbox

    def unsubscribe(self, outbox: queue.Queue) -> None:
        with self._lock:
            if outbox in self._subscribers:
                self._subscribers.remove(outbox)

    def emit(self, event: Event) -> None:
        with self._lock:
            for outbox in list(self._subscribers):
                try:
                    outbox.put_nowait(event)
                except queue.Full:
                    pass  # slow consumer: drop rather than block the agent

    # ── submission ────────────────────────────────────────────────────
    def send(self, text: str) -> None:
        def deliver(event: Event) -> None:
            self.emit(event)
            if event.get("type") == "submit_prompt":
                # /skill wants its expanded prompt run as a fresh turn
                inner = event["text"]
                threading.Thread(
                    target=self.controller.submit, args=(inner, deliver_outer), daemon=True
                ).start()

        def deliver_outer(event: Event) -> None:
            self.emit(event)

        self.controller.submit(text, deliver)

    # ── approval bridge (called on the agent thread) ──────────────────
    def attach_approval_provider(self) -> None:
        def provider(action: str, summary: str):
            request_id = f"ap_{secrets.token_hex(6)}"
            answered = threading.Event()
            slot: Dict[str, object] = {"decision": False, "remember": False}
            self._approval_waiters[request_id] = slot
            self.emit({
                "type": "approval_request",
                "id": request_id,
                "action": action,
                "summary": summary,
            })
            answered.wait(timeout=3600)  # wait for POST /api/approve
            self._approval_waiters.pop(request_id, None)
            return bool(slot["decision"]), slot["remember"]

        set_provider(provider)

    def resolve_approval(self, request_id: str, decision: bool, remember: bool = False) -> bool:
        # The waiting provider polls its slot via the Event; we keep it simple:
        # store the answer and wake the waiter through a synthetic event loop.
        slot = self._approval_waiters.get(request_id)
        if slot is None:
            return False
        slot["decision"] = bool(decision)
        slot["remember"] = bool(remember)
        self.emit({"type": "approval_resolved", "id": request_id, "approved": bool(decision)})
        return True


class DesktopHandler(BaseHTTPRequestHandler):
    hub: DesktopHub = None  # injected by serve()
    token: str = ""

    def log_message(self, fmt, *args):  # quiet access log
        log.debug("desktop " + fmt % args)

    # ── helpers ───────────────────────────────────────────────────────
    def _authorized(self) -> bool:
        from urllib.parse import parse_qs, urlparse
        query = parse_qs(urlparse(self.path).query)
        supplied = (query.get("t") or [""])[0]
        return secrets.compare_digest(supplied, self.token)

    def _deny(self) -> None:
        self.send_response(403)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error": "forbidden"}')

    def _json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except (ValueError, UnicodeDecodeError):
            return {}

    def _serve_static(self, name: str) -> None:
        target = (STATIC_DIR / name).resolve()
        if not target.is_file() or STATIC_DIR.resolve() not in target.parents:
            self.send_error(404)
            return
        content = target.read_bytes()
        ctype = "text/html; charset=utf-8"
        if target.suffix == ".js":
            ctype = "text/javascript; charset=utf-8"
        elif target.suffix == ".css":
            ctype = "text/css; charset=utf-8"
        elif target.suffix == ".svg":
            ctype = "image/svg+xml"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    # ── GET ───────────────────────────────────────────────────────────
    def do_GET(self):
        from urllib.parse import urlparse
        path = urlparse(self.path).path
        if not self._authorized():
            return self._deny()
        if path in ("/", "/index.html"):
            return self._serve_static("index.html")
        if path.endswith(".js") or path.endswith(".css") or path.endswith(".svg"):
            return self._serve_static(path.lstrip("/"))
        if path == "/api/state":
            controller = self.hub.controller
            pid, _, model = get_active_provider_info()
            return self._json({
                "session_id": controller.session_id,
                "running": controller.is_running(),
                "mode": get_active_mode().upper(),
                "provider": pid,
                "model": model,
                "version": _version(),
            })
        if path == "/api/sessions":
            from rex.sessions import session_store
            items = []
            for meta in session_store.list()[:20]:
                items.append({
                    "id": meta["id"],
                    "title": meta.get("title") or "Percakapan baru",
                    "model": meta.get("model"),
                    "updated_at": (meta.get("updated_at") or "")[:16],
                })
            return self._json({"sessions": items})
        if path == "/api/events":
            return self._stream_events()
        if path == "/api/files":
            from rex.config import WORKSPACE_DIR
            files = []
            for f in sorted(WORKSPACE_DIR.rglob("*")):
                if f.is_file() and ".rex" not in f.parts and "node_modules" not in f.parts:
                    try:
                        files.append(f.relative_to(WORKSPACE_DIR).as_posix())
                    except ValueError:
                        continue
                if len(files) >= 200:
                    break
            return self._json({"files": files})
        if path == "/api/usage":
            return self._json(_usage_snapshot(self.hub.controller))
        if path == "/api/settings":
            from rex.desktop.settings_api import settings_get
            return self._json(settings_get())
        if path == "/api/providers":
            from rex.desktop.settings_api import providers_list
            return self._json(providers_list())
        if path == "/api/onboarding":
            from rex.desktop.settings_api import onboarding_status
            return self._json(onboarding_status())
        self.send_error(404)

    def _stream_events(self) -> None:
        outbox = self.hub.subscribe()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        import time
        try:
            last_ping = time.monotonic()
            while True:
                try:
                    event = outbox.get(timeout=QUEUE_TIMEOUT)
                    payload = json.dumps(event, ensure_ascii=False, default=str)
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                except queue.Empty:
                    if time.monotonic() - last_ping >= SSE_PING_SEC:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        last_ping = time.monotonic()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, OSError):
            pass  # client closed the tab/window
        finally:
            self.hub.unsubscribe(outbox)

    # ── POST ──────────────────────────────────────────────────────────
    def do_POST(self):
        from urllib.parse import urlparse
        path = urlparse(self.path).path
        if not self._authorized():
            return self._deny()
        body = self._body()
        hub = self.hub
        controller = hub.controller

        if path == "/api/send":
            text = str(body.get("text") or "")
            if not text.strip():
                return self._json({"ok": False, "error": "empty"})
            threading.Thread(target=hub.send, args=(text,), daemon=True).start()
            return self._json({"ok": True})
        if path == "/api/abort":
            controller.abort()
            return self._json({"ok": True})
        if path == "/api/approve":
            ok = hub.resolve_approval(
                str(body.get("id") or ""), bool(body.get("decision")), bool(body.get("remember"))
            )
            return self._json({"ok": ok})
        if path == "/api/mode":
            mode = str(body.get("mode") or "").lower()
            if mode not in ("plan", "build"):
                return self._json({"ok": False, "error": "mode?"}, 400)
            set_active_mode(mode)
            hub.emit({"type": "mode_changed", "mode": mode.upper()})
            return self._json({"ok": True, "mode": mode.upper()})
        if path == "/api/sessions":
            action = str(body.get("action") or "")
            session_id = str(body.get("id") or "")
            if action == "new":
                event = controller.new_session()
                hub.emit(event)
                return self._json({"ok": True, "session_id": controller.session_id})
            if action == "resume":
                event = controller.resume_session(session_id)
                hub.emit(event)
                return self._json({"ok": event.get("type") == "session_changed"})
            if action == "delete":
                hub.emit(controller.delete_session(session_id))
                return self._json({"ok": True})
            return self._json({"ok": False, "error": "action?"}, 400)
        if path == "/api/settings":
            from rex.desktop.settings_api import settings_update
            return self._json(settings_update(body))
        if path == "/api/providers":
            from rex.desktop.settings_api import provider_mutate
            return self._json(provider_mutate(body))
        if path == "/api/keys":
            from rex.desktop.settings_api import key_write
            return self._json(key_write(body))
        if path == "/api/onboarding":
            from rex.desktop.settings_api import onboarding_complete
            return self._json(onboarding_complete(body))
        if path.startswith("/api/providers/") and path.endswith("/test"):
            pid = path[len("/api/providers/"):-len("/test")]
            from rex.desktop.settings_api import provider_test
            return self._json(provider_test(pid, str(body.get("model") or "") or None))
        self.send_error(404)


def _version() -> str:
    import rex
    return rex.__version__


def _usage_snapshot(controller) -> dict:
    """Session token usage for the usage footer (never raises)."""
    tokens = 0
    cost = 0.0
    try:
        sess = getattr(controller, "session", None) or {}
        if isinstance(sess, dict):
            usage = sess.get("usage") or {}
            tokens = int(usage.get("total_tokens", 0) or 0)
            cost = float(usage.get("cost_usd", 0.0) or 0.0)
    except Exception:  # noqa: BLE001 — footer is cosmetic
        pass
    return {"ok": True, "total_tokens": tokens, "cost_usd": cost}


def serve(open_window: bool = True, host: str = "127.0.0.1", browser: bool = False) -> Dict[str, object]:
    """
    Start Rex Desktop: build the controller, host the UI, optionally open
    the native window (or a plain browser tab when browser=True). Blocks
    until the server stops. Returns nothing on normal shutdown.
    """
    controller = ChatController()
    hub = DesktopHub(controller)
    hub.attach_approval_provider()

    handler = type("RexDesktopHandler", (DesktopHandler,), {"hub": hub, "token": secrets.token_hex(16)})
    server = ThreadingHTTPServer((host, 0), handler)  # port 0 = free port
    port = server.server_address[1]
    url = f"http://{host}:{port}/?t={handler.token}"
    log.info("rex desktop listening on %s", url)

    if open_window:
        threading.Thread(target=lambda: _safe_open(url, browser=browser), daemon=True).start()

    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        reset_session_allows()
        set_provider(None)
        server.server_close()
    return {"url": url}


def _safe_open(url: str, browser: bool = False) -> None:
    try:
        import webbrowser
        if browser:
            webbrowser.open(url)
            return
        from rex.desktop.window import open_app_window
        open_app_window(url)
    except Exception as exc:
        log.warning("desktop window launch failed: %s", exc)
