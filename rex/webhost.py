"""
rex.webhost
HTTP host for the GitHub webhook receiver: exposes the webhook engine
(`rex.webhooks.handle_github_event`) over HTTP so GitHub / CI platforms can
deliver PR events to Rex Code ("run Rex from CI").

Endpoints:
    POST /webhook/github   — GitHub webhook delivery (signature-verified)
    GET  /healthz          — liveness probe for monitoring / reverse proxies

Run:
    python -m rex.webhost               # host/port from config.json -> webhook
    python -m rex.webhost --port 9000   # override port
    rex --serve-webhook                 # classic CLI flag

Configuration lives under `webhook` in config.json:

    "webhook": {
        "enabled": true,        # master switch (false -> host refuses to start)
        "host": "127.0.0.1",    # bind address (0.0.0.0 to expose; use TLS proxy)
        "port": 8765,
        ...                     # see rex/webhooks.py for the rest
    }

Security:
    - Deny by default: `enabled: false` -> SystemExit(2), no listener ever.
    - Binds 127.0.0.1 by default; exposing to a network is a deliberate act.
    - Every delivery must carry a valid X-Hub-Signature-256 HMAC — verified
      constant-time by the engine before anything is dispatched.
    - Bodies larger than MAX_BODY_BYTES are rejected before being read.
"""

import argparse
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from rex.config import load_config, normalize_config
from rex.webhooks import WebhookError, handle_github_event

log = logging.getLogger("rex.webhost")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

# GitHub payloads are small (typical PR webhook < 100 KB). Hard cap first.
MAX_BODY_BYTES = 1_000_000  # 1 MB


class RexWebhookHandler(BaseHTTPRequestHandler):
    """Routes POST /webhook/github and GET /healthz. Response contract:

        200 {"status": "ignored", ...}  valid delivery, nothing to do
        202 {"status": "accepted"}      review dispatched (background thread)
        400 {"status": "bad_request"}   missing/invalid Content-Length
        403 {"status": "forbidden"}     invalid signature or bad payload
        404 {"status": "not_found"}     unknown path
        413 {"status": "payload_too_large"}
        500 {"status": "internal_error"} engine crashed
    """

    # Do not advertise the Python version in response headers.
    server_version = "RexWebhost/1.0"

    def do_POST(self) -> None:
        if self.path != "/webhook/github":
            return self._send_json(404, {"status": "not_found"})

        event = self.headers.get("X-GitHub-Event", "")
        signature = self.headers.get("X-Hub-Signature-256", "")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._send_json(400, {"status": "bad_request"})

        if length <= 0:
            return self._send_json(400, {"status": "bad_request"})
        if length > MAX_BODY_BYTES:
            return self._send_json(413, {"status": "payload_too_large"})

        body = self.rfile.read(length)
        try:
            result = handle_github_event(event, body, signature)
        except WebhookError:
            # Invalid signature / bad JSON — reject without detail.
            return self._send_json(403, {"status": "forbidden"})
        except Exception:
            log.exception("webhook handler crashed")
            return self._send_json(500, {"status": "internal_error"})

        status = 202 if result.get("status") == "accepted" else 200
        self._send_json(status, result)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            return self._send_json(200, {"status": "ok", "service": "rex-webhost"})
        self._send_json(404, {"status": "not_found"})

    # --- plumbing ------------------------------------------------------------

    def _send_json(self, code: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args) -> None:
        log.debug("webhost " + fmt, *args)
    def log_message(self, fmt: str, *args) -> None:
        log.debug("webhost " + fmt, *args)


def webhost_settings() -> dict:
    """Return the `webhook` section with host/port defaults applied safely."""
    cfg = normalize_config(load_config())
    webhook = dict(cfg.get("webhook", {}))
    webhook["host"] = str(webhook.get("host") or DEFAULT_HOST)
    try:
        webhook["port"] = int(webhook.get("port") or DEFAULT_PORT)
    except (TypeError, ValueError):
        webhook["port"] = DEFAULT_PORT
    return webhook


def create_server(host: str, port: int) -> ThreadingHTTPServer:
    """Create (but do not serve) the ThreadingHTTPServer — one thread per request."""
    return ThreadingHTTPServer((host, port), RexWebhookHandler)


def run_webhost(host: Optional[str] = None, port: Optional[int] = None) -> None:
    """
    Entry point: read settings, refuse when disabled, then serve until
    interrupted (Ctrl+C).
    """
    webhook = normalize_config(load_config()).get("webhook", {})

    if not webhook.get("enabled", False):
        log.error("webhook.enabled=false di config — host menolak start (deny by default)")
        raise SystemExit(2)

    host = host or webhook.get("host") or DEFAULT_HOST
    port = int(port or webhook.get("port") or DEFAULT_PORT)

    server = create_server(host, port)
    log.info("rex-webhost listening on http://%s:%d (Ctrl+C to stop)", host, port)
    print(f"rex-webhost listening on http://{host}:{port} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("webhook host stopped by user")
    finally:
        server.server_close()


def main(argv: Optional[list] = None) -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(
        prog="rex.webhost", description="Rex Code — GitHub webhook receiver host")
    parser.add_argument("--host", default=None,
                        help="Bind address (default: config webhook.host / 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None,
                        help="Port (default: config webhook.port / 8765)")
    args = parser.parse_args(argv)
    run_webhost(host=args.host, port=args.port)


if __name__ == "__main__":
    main()