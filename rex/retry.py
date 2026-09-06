"""
rex.retry
=========
Shared HTTP retry discipline for all providers.

Rules:
- Retry transient failures only: HTTP 429 / 500 / 502 / 503 / 504,
  timeouts, and connection errors.
- Never retry configuration errors: 400 / 401 / 403 / 404 — the user must
  fix their key or URL; retrying just burns time.
- Exponential backoff with full jitter, capped, so parallel sessions do
  not synchronize their retries into a thundering herd.
- Sleeping honors cooperative abort via a probe callable.
"""

from __future__ import annotations

import random
import time
from typing import Callable, Dict, Optional

RETRYABLE_HTTP_CODES = frozenset({429, 500, 502, 503, 504})


def is_retryable_http(code: int) -> bool:
    return int(code) in RETRYABLE_HTTP_CODES


def is_retryable_exception(exc: BaseException) -> bool:
    """Classify exceptions conservatively: only transient causes retry."""
    if _is_retryable_http_error(exc):
        return True
    if isinstance(exc, TimeoutError):
        return True
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    # urllib: URLError / socket.timeout; httpx: ConnectError / ReadError / RemoteProtocolError
    transient_markers = (
        "timeout", "timed out", "connection", "temporarily unavailable",
        "connectionreset", "connectionaborted", "broken pipe", "eof",
    )
    if any(marker in name for marker in transient_markers):
        return True
    return any(marker in text for marker in transient_markers)


def compute_backoff(attempt: int, base_delay: float, max_delay: float = 30.0) -> float:
    """Exponential backoff with full jitter. attempt is 0-based."""
    raw = min(max_delay, base_delay * (2 ** max(0, attempt)))
    return random.uniform(0.0, raw) if raw > 0 else 0.0


def sleep_with_abort(seconds: float, abort_probe: Optional[Callable[[], bool]] = None) -> bool:
    """Sleep in small slices, bailing out early when abort_probe() turns True.
    Returns False if the sleep was interrupted by an abort request."""
    deadline = time.monotonic() + max(0.0, seconds)
    while True:
        if abort_probe is not None and abort_probe():
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True
        time.sleep(min(0.2, remaining))


def run_with_retries(
    operation: Callable[[], object],
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    abort_probe: Optional[Callable[[], bool]] = None,
    log: Optional[Callable[[str], None]] = None,
) -> object:
    """
    Execute operation() with retry/backoff. Raises the last exception when
    retries are exhausted or the failure is non-retryable. Abort-aware:
    when abort_probe() returns True, the pending operation's exception is
    raised immediately (cooperative cancellation wins).
    """
    attempts = max(1, int(max_retries) + 1)
    last_error: Optional[BaseException] = None
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001 — classified below
            last_error = exc
            retryable = is_retryable_exception(exc) or _is_retryable_http_error(exc)
            if not retryable or attempt == attempts - 1 or not sleep_with_abort(
                compute_backoff(attempt, base_delay), abort_probe
            ):
                raise
            if log is not None:
                log(
                    f"retry: transient failure ({type(exc).__name__}), "
                    f"attempt {attempt + 2}/{attempts}"
                )
    raise last_error  # pragma: no cover — loop always returns or raises


def _is_retryable_http_error(exc: BaseException) -> bool:
    """Detect HTTPError / HTTPStatusError style failures and check the code."""
    code = getattr(exc, "code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    if code is None:
        text = str(exc)
        for candidate in RETRYABLE_HTTP_CODES:
            if f" {candidate} " in text or f" {candidate}:" in text or text.startswith(str(candidate)):
                return True
        return False
    return is_retryable_http(code)


def parse_usage(data: Optional[Dict]) -> Optional[Dict[str, int]]:
    """
    Normalize usage payloads into {prompt_tokens, completion_tokens, total_tokens}.
    Accepts either a full API response (with a "usage" key) or a raw usage
    dict itself. Returns None when no usage data is present (common for some
    streams/providers).
    """
    if not isinstance(data, dict):
        return None
    usage = data.get("usage")
    if not isinstance(usage, dict):
        usage = data if {"prompt_tokens", "input_tokens"} & data.keys() else None
    if not isinstance(usage, dict):
        return None
    result = {
        "prompt_tokens": int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or usage.get("output_tokens") or 0),
    }
    total = usage.get("total_tokens")
    result["total_tokens"] = int(total) if total is not None else result["prompt_tokens"] + result["completion_tokens"]
    if result["total_tokens"] <= 0 and result["prompt_tokens"] <= 0 and result["completion_tokens"] <= 0:
        return None
    return result
