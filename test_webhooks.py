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

    print("\nWebhook checks 22/22 PASS")


if __name__ == "__main__":
    main()