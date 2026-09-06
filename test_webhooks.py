"""Self-check GitHub webhook receiver. Run: python test_webhooks.py"""

import hashlib
import hmac
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rex.webhooks import (
    WebhookError,
    _run_and_comment,
    build_review_prompt,
    extract_pr_context,
    handle_github_event,
    is_event_allowed,
    verify_github_signature,
)
from rex.webhost import run_webhost, webhost_settings


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


def sign(payload: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def pr_payload(action="opened", repo="acme/web", number=42, title="Tambah fitur", body="desc"):
    return {
        "action": action,
        "repository": {"full_name": repo},
        "pull_request": {"number": number, "title": title, "body": body,
                         "head": {"ref": "feature/x"}},
    }


SETTINGS = {
    "enabled": True,
    "secret_env": "GITHUB_WEBHOOK_SECRET",
    "token_env": "GITHUB_TOKEN",
    "events": ["pull_request", "issue_comment"],
    "trigger_word": "/rex",
    "auto_review": True,
    "max_diff_chars": 30000,
}


def main():
    # 1. Signature verification
    payload = b'{"hello":"world"}'
    check("valid signature accepted", verify_github_signature(payload, sign(payload, "s3cret"), "s3cret"))
    check("wrong secret rejected", not verify_github_signature(payload, sign(payload, "wrong"), "s3cret"))
    check("missing header rejected", not verify_github_signature(payload, "", "s3cret"))
    check("missing secret rejected", not verify_github_signature(payload, sign(payload, "s3cret"), ""))
    check("tampered payload rejected",
          not verify_github_signature(b'{"hello":"evil"}', sign(payload, "s3cret"), "s3cret"))

    # 2. Event filtering
    check("pull_request allowed", is_event_allowed("pull_request", SETTINGS))
    check("unknown event ignored", not is_event_allowed("deployment", SETTINGS))

    # 3. PR context extraction
    ctx = extract_pr_context("pull_request", pr_payload())
    check("PR opened is actionable", ctx is not None and ctx["pr_number"] == 42 and ctx["trigger"] == "auto_review")
    check("PR closed ignored", extract_pr_context("pull_request", pr_payload(action="closed")) is None)

    comment_payload = {
        "action": "created",
        "repository": {"full_name": "acme/web"},
        "issue": {"number": 7, "title": "PR 7", "body": "abc", "pull_request": {}},
        "comment": {"body": "/rex tolong review PR ini"},
    }
    ctx = extract_pr_context("issue_comment", comment_payload)
    check("comment with trigger actionable", ctx is not None and ctx["trigger"] == "comment")

    no_trigger = json.loads(json.dumps(comment_payload))
    no_trigger["comment"]["body"] = "terima kasih!"
    check("comment without trigger ignored", extract_pr_context("issue_comment", no_trigger) is None)

    issue_payload = json.loads(json.dumps(comment_payload))
    issue_payload["issue"].pop("pull_request")
    check("issue (non-PR) comment ignored", extract_pr_context("issue_comment", issue_payload) is None)

    # 4. Review prompt building + diff truncation
    context = {"repo": "acme/web", "pr_number": 42, "title": "T", "body": "B",
               "branch": "feature/x", "diff": "+def foo(): ..."}
    prompt = build_review_prompt(context, SETTINGS)
    check("prompt embeds PR info", "acme/web" in prompt and "#42" in prompt and "feature/x" in prompt)
    small = {"max_diff_chars": 50}
    truncated = build_review_prompt({**context, "diff": "x" * 500}, small)
    check("diff truncated in prompt", "dipotong" in truncated)

    # 5. handle_github_event: dispatch + security
    payload_bytes = json.dumps(pr_payload()).encode()

    with patch.dict(os.environ, {"GITHUB_WEBHOOK_SECRET": "s3cret", "GITHUB_TOKEN": "ghp_x"}, clear=True), \
         patch("rex.webhooks.webhook_settings", return_value=SETTINGS), \
         patch("rex.webhooks.threading.Thread") as fake_thread:
        result = handle_github_event("pull_request", payload_bytes, sign(payload_bytes, "s3cret"))
    check("valid delivery accepted", result["status"] == "accepted")
    check("review thread spawned", fake_thread.return_value.start.called)

    with patch.dict(os.environ, {"GITHUB_WEBHOOK_SECRET": "s3cret", "GITHUB_TOKEN": "ghp_x"}, clear=True), \
         patch("rex.webhooks.webhook_settings", return_value=SETTINGS):
        try:
            handle_github_event("pull_request", payload_bytes, sign(payload_bytes, "WRONG"))
            check("bad signature raises WebhookError", False)
        except WebhookError:
            check("bad signature raises WebhookError", True)

    with patch.dict(os.environ, {"GITHUB_WEBHOOK_SECRET": "s3cret", "GITHUB_TOKEN": "ghp_x"}, clear=True), \
         patch("rex.webhooks.webhook_settings", return_value={**SETTINGS, "auto_review": False}):
        result = handle_github_event("pull_request", payload_bytes, sign(payload_bytes, "s3cret"))
    check("auto_review disabled ignores PR open", result["status"] == "ignored")

    with patch.dict(os.environ, {"GITHUB_WEBHOOK_SECRET": "s3cret"}, clear=True), \
         patch("rex.webhooks.webhook_settings", return_value=SETTINGS), \
         patch("rex.webhooks.threading.Thread") as fake_thread:
        result = handle_github_event("pull_request", payload_bytes, sign(payload_bytes, "s3cret"))
    check("missing token still accepted", result["status"] == "accepted" and not fake_thread.return_value.start.called)

    # 6. _run_and_comment posts the review
    with patch("rex.webhooks.fetch_pr_info", return_value={"title": "T", "body": "B", "branch": "b"}), \
         patch("rex.webhooks.fetch_pr_diff", return_value="+code"), \
         patch("rex.webhooks.run_review", return_value="Review bagus, ada bug di baris 3."), \
         patch("rex.webhooks.post_issue_comment", return_value=True) as post:
        _run_and_comment({"repo": "acme/web", "pr_number": 42}, SETTINGS, "ghp_x")
    posted = post.call_args[0][3]
    check("review comment posted", "Rex Code Review" in posted and "Review bagus" in posted)

    # 7. Failure posts a brief error comment (type only, no message)
    with patch("rex.webhooks.fetch_pr_info", side_effect=RuntimeError("boom with gh p_ token inside")), \
         patch("rex.webhooks.post_issue_comment", return_value=True) as post:
        _run_and_comment({"repo": "acme/web", "pr_number": 42}, SETTINGS, "ghp_x")
    posted = post.call_args[0][3]
    check("failure posts error comment", "RuntimeError" in posted and "gh p_" not in posted.replace(" ", " "))

    # 8. HTTP host (rex.webhost) — routing over real HTTP, engine stubbed.
    import threading as _threading
    from http.server import ThreadingHTTPServer

    def make_payload_bytes():
        return json.dumps(pr_payload()).encode()

    # The engine reads config from disk; point it at our test settings for
    # every request below (patch the symbol the handler looks up at runtime).
    import socket as _socket
    import rex.webhost as webhost_mod
    import rex.webhooks as wh

    def fake_engine(event, body, signature):
        with patch.object(wh, "webhook_settings", return_value=SETTINGS), \
             patch.dict(os.environ, {"GITHUB_WEBHOOK_SECRET": "s3cret", "GITHUB_TOKEN": "ghp_x"}), \
             patch.object(wh.threading, "Thread"):
            return handle_github_event(event, body, signature)

    engine_patch = patch.object(webhost_mod, "handle_github_event", side_effect=fake_engine)
    engine_patch.start()

    server = ThreadingHTTPServer(("127.0.0.1", 0), webhost_mod.RexWebhookHandler)
    port = server.server_address[1]
    server_thread = _threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    import httpx

    base = f"http://127.0.0.1:{port}"

    # healthz responds 200 with service identity
    r = httpx.get(f"{base}/healthz", timeout=5)
    check("healthz returns 200 ok", r.status_code == 200 and r.json()["status"] == "ok"
          and r.json()["service"] == "rex-webhost")

    # unknown GET path -> 404
    r = httpx.get(f"{base}/nope", timeout=5)
    check("unknown GET path 404", r.status_code == 404 and r.json()["status"] == "not_found")

    # unknown POST path -> 404
    r = httpx.post(f"{base}/other", content=b"{}", timeout=5)
    check("unknown POST path 404", r.status_code == 404)

    # invalid signature -> 403 forbidden
    payload_bytes2 = make_payload_bytes()
    r = httpx.post(f"{base}/webhook/github", content=payload_bytes2,
                   headers={"X-GitHub-Event": "pull_request",
                            "X-Hub-Signature-256": sign(payload_bytes2, "WRONG")}, timeout=5)
    check("invalid signature 403", r.status_code == 403 and r.json()["status"] == "forbidden")

    # valid delivery -> 202 accepted (engine thread mocked, never spawned)
    payload_bytes2 = make_payload_bytes()
    r = httpx.post(f"{base}/webhook/github", content=payload_bytes2,
                   headers={"X-GitHub-Event": "pull_request",
                            "X-Hub-Signature-256": sign(payload_bytes2, "s3cret")}, timeout=5)
    check("valid delivery 202 accepted", r.status_code == 202 and r.json()["status"] == "accepted")

    # event not in allowlist -> 200 ignored
    payload_bytes2 = json.dumps({"action": "x", "repository": {}}).encode()
    r = httpx.post(f"{base}/webhook/github", content=payload_bytes2,
                   headers={"X-GitHub-Event": "deployment",
                            "X-Hub-Signature-256": sign(payload_bytes2, "s3cret")}, timeout=5)
    check("non-allowlisted event 200 ignored", r.status_code == 200 and r.json()["status"] == "ignored")

    # no Content-Length body -> 400 (httpx always sets it; emulate raw socket)
    import socket as _socket
    s = _socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(b"POST /webhook/github HTTP/1.1\r\nHost: x\r\nContent-Length: 0\r\n\r\n")
    chunks = []
    while True:
        data = s.recv(4096)
        if not data:
            break
        chunks.append(data)
    resp = b"".join(chunks).decode("utf-8", "replace")
    s.close()
    check("empty body 400 bad_request", " 400 " in resp and "bad_request" in resp)

    # run_webhost refuses to start when webhook.enabled=false (deny by default)
    with patch.object(webhost_mod, "normalize_config",
                      return_value={"webhook": {**SETTINGS, "enabled": False}}), \
         patch.object(webhost_mod, "create_server") as fake_create:
        try:
            run_webhost()
            check("disabled webhook refuses to start", False)
        except SystemExit as exc:
            check("disabled webhook refuses to start", exc.code == 2 and not fake_create.called)
        except _Exit:
            check("disabled webhook refuses to start", False)

    # webhost_settings applies host/port defaults safely
    with patch.object(webhost_mod, "normalize_config",
                      return_value={"webhook": {**SETTINGS, "host": None, "port": "garbage"}}):
        ws = webhost_settings()
    check("webhost defaults host/port", ws["host"] == "127.0.0.1" and ws["port"] == 8765)

    engine_patch.stop()
    server.shutdown()
    server.server_close()
    server_thread.join(timeout=5)

    print("\nWebhook checks 30/30 PASS")


if __name__ == "__main__":
    main()