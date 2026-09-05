"""
rex.webhooks
GitHub webhook receiver: run Rex Code on Pull Request events and post the
review back as a PR comment ("run Rex from CI").

Configuration lives under `webhook` in config.json:

    "webhook": {
        "enabled": true,
        "secret_env": "GITHUB_WEBHOOK_SECRET",   # env var with the webhook secret
        "token_env": "GITHUB_TOKEN",             # env var with a GitHub API token
        "events": ["pull_request", "issue_comment"],
        "trigger_word": "/rex",                  # comment trigger (issue_comment)
        "auto_review": true,                     # review PRs on open/synchronize
        "max_diff_chars": 30000
    }

Security: every request must carry a valid X-Hub-Signature-256 HMAC or it is
rejected. The GitHub token is read from the environment and never logged; it
is also stripped from child process environments by the sandbox.
"""

import hashlib
import hmac
import json
import logging
import os
import threading
from typing import Dict, Optional

import httpx

from rex.config import load_config, normalize_config, set_active_mode
from rex.core import RexAgent

log = logging.getLogger("rex.webhooks")

GITHUB_API = "https://api.github.com"


class WebhookError(Exception):
    """Raised for requests that must be rejected (bad signature, bad payload)."""


def webhook_settings() -> dict:
    cfg = normalize_config(load_config())
    return cfg.get("webhook", {})


# --- Signature verification ------------------------------------------------

def verify_github_signature(payload: bytes, signature_header: str, secret: str) -> bool:
    """Constant-time HMAC-SHA256 check of the X-Hub-Signature-256 header."""
    if not signature_header or not secret:
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


# --- Event filtering & context extraction ----------------------------------

def is_event_allowed(event: str, settings: dict) -> bool:
    allowed = [str(item).lower() for item in settings.get("events") or []]
    return event.lower() in allowed


def _is_rex_invocation(body: str, trigger_word: str) -> bool:
    if not trigger_word:
        return True
    return trigger_word.lower() in (body or "").lower()


def extract_pr_context(event: str, payload: dict) -> Optional[dict]:
    """
    Return actionable PR context from a GitHub webhook payload, or None when
    the event should be ignored (wrong action, not a PR, not a Rex trigger).
    """
    repository = payload.get("repository") or {}
    repo = repository.get("full_name")

    if event == "pull_request":
        pr = payload.get("pull_request") or {}
        action = payload.get("action")
        if action not in ("opened", "synchronize"):
            return None
        if not repo or not pr.get("number"):
            return None
        return {
            "repo": repo,
            "pr_number": int(pr["number"]),
            "title": pr.get("title") or "",
            "body": pr.get("body") or "",
            "branch": (pr.get("head") or {}).get("ref") or "",
            "trigger": "auto_review",
        }

    if event == "issue_comment":
        issue = payload.get("issue") or {}
        if "pull_request" not in issue:  # only comments on PRs
            return None
        if payload.get("action") != "created":
            return None
        comment = payload.get("comment") or {}
        body = comment.get("body") or ""
        settings = webhook_settings()
        if not _is_rex_invocation(body, settings.get("trigger_word") or "/rex"):
            return None
        if not repo or not issue.get("number"):
            return None
        return {
            "repo": repo,
            "pr_number": int(issue["number"]),
            "title": issue.get("title") or "",
            "body": issue.get("body") or "",
            "branch": "",
            "trigger": "comment",
        }

    return None


# --- GitHub API helpers (httpx, no new dependencies) -----------------------

def _github_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def fetch_pr_info(repo: str, pr_number: int, token: str) -> dict:
    with httpx.Client(timeout=30) as client:
        response = client.get(
            f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}",
            headers=_github_headers(token),
        )
        response.raise_for_status()
        data = response.json()
    return {
        "repo": repo,
        "pr_number": pr_number,
        "title": data.get("title") or "",
        "body": data.get("body") or "",
        "branch": (data.get("head") or {}).get("ref") or "",
    }


def fetch_pr_diff(repo: str, pr_number: int, token: str) -> str:
    with httpx.Client(timeout=60) as client:
        response = client.get(
            f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}",
            headers={**_github_headers(token), "Accept": "application/vnd.github.v3.diff"},
        )
        response.raise_for_status()
        return response.text


def post_issue_comment(repo: str, pr_number: int, token: str, body: str) -> bool:
    with httpx.Client(timeout=30) as client:
        response = client.post(
            f"{GITHUB_API}/repos/{repo}/issues/{pr_number}/comments",
            headers=_github_headers(token),
            json={"body": body},
        )
        response.raise_for_status()
    return True


# --- Review execution ------------------------------------------------------

REVIEW_PROMPT = """Anda adalah Rex Code, code reviewer otomatis untuk Pull Request #{pr} di repo {repo}.
Cabang: {branch}
Judul PR: {title}
Deskripsi PR: {body}

Diff perubahan:
{diff}

Tugas Anda:
1. Ringkas perubahan dalam 3-5 poin.
2. Temukan masalah keamanan, bug potensial, atau anti-pattern.
3. Berikan saran perbaikan konkret (dengan nama file/baris jika memungkinkan).
4. Sebutkan hal yang sudah bagus.

Jawab dalam Bahasa Indonesia, padat dan terstruktur. Jangan mengubah file apa pun — ini murni review."""


def _truncate_diff(diff: str, max_chars: int) -> str:
    if len(diff) <= max_chars:
        return diff
    return diff[: max(0, max_chars - 60)] + "\n\n...[diff dipotong]"


def build_review_prompt(context: dict, settings: dict) -> str:
    max_chars = settings.get("max_diff_chars") or 30000
    return REVIEW_PROMPT.format(
        pr=context["pr_number"],
        repo=context["repo"],
        branch=context.get("branch") or "-",
        title=context.get("title") or "-",
        body=(context.get("body") or "-")[:2000],
        diff=_truncate_diff(context.get("diff") or "(diff kosong)", max_chars),
    )


def run_review(context: dict, settings: dict) -> str:
    """Run RexAgent in BUILD mode against the PR context; return the review text."""
    set_active_mode("build")
    agent = RexAgent()
    prompt = build_review_prompt(context, settings)
    return agent.run(prompt)


def _run_and_comment(context: dict, settings: dict, token: str):
    """Background job: gather PR info + diff, run Rex, post the review comment."""
    try:
        info = fetch_pr_info(context["repo"], context["pr_number"], token)
        diff = fetch_pr_diff(context["repo"], context["pr_number"], token)
        context = {**context, **info, "diff": diff}
        review = run_review(context, settings)
        body = f"### 🦖 Rex Code Review\n\n{review}"
        post_issue_comment(context["repo"], context["pr_number"], token, body)
        log.info("webhook review posted repo=%s pr=%s", context["repo"], context["pr_number"])
    except Exception as exc:
        # Log only the type — the message could echo API responses with tokens.
        log.error("webhook review failed type=%s repo=%s pr=%s",
                  type(exc).__name__, context.get("repo"), context.get("pr_number"))
        try:
            post_issue_comment(
                context["repo"], context["pr_number"], token,
                f"### 🦖 Rex Code Review\n\nGagal menyelesaikan review: **{type(exc).__name__}**. "
                f"Periksa logs/rex.log untuk detail.",
            )
        except Exception:
            log.error("webhook error comment failed type=%s", type(exc).__name__)


# --- Entry point -----------------------------------------------------------

def handle_github_event(event: str, payload_bytes: bytes, signature: str) -> dict:
    """
    Verify, filter, and dispatch a GitHub webhook delivery.
    Returns a status dict; the actual review runs in a background thread.
    """
    settings = webhook_settings()
    secret = os.getenv(settings.get("secret_env") or "GITHUB_WEBHOOK_SECRET", "")
    if not verify_github_signature(payload_bytes, signature, secret):
        raise WebhookError("Signature webhook tidak valid.")

    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise WebhookError("Payload JSON tidak valid.")

    if not is_event_allowed(event, settings):
        return {"status": "ignored", "reason": "event_not_allowed"}

    context = extract_pr_context(event, payload)
    if not context:
        return {"status": "ignored", "reason": "not_actionable"}

    if context["trigger"] == "auto_review" and not settings.get("auto_review", True):
        return {"status": "ignored", "reason": "auto_review_disabled"}

    token = os.getenv(settings.get("token_env") or "GITHUB_TOKEN", "")
    if not token:
        log.error("webhook accepted but GITHUB_TOKEN kosong")
        return {"status": "accepted", "note": "token_missing"}

    thread = threading.Thread(
        target=_run_and_comment,
        args=(context, settings, token),
        daemon=True,
        name=f"rex-webhook-{context['repo']}-{context['pr_number']}",
    )
    thread.start()
    return {"status": "accepted"}