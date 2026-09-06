"""Self-check for the retry/usage foundation. Run: python test_retry.py"""

import sys
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rex.retry import (
    compute_backoff,
    is_retryable_exception,
    is_retryable_http,
    parse_usage,
    run_with_retries,
)
from rex.providers.base import Usage, LLMResponse


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


def http_error(code):
    return urllib.error.HTTPError(url="http://x", code=code, msg="e", hdrs=None, fp=None)


def main():
    # ── Classification ────────────────────────────────────────────────
    for code in (429, 500, 502, 503, 504):
        check(f"http {code} retryable", is_retryable_http(code))
    for code in (400, 401, 403, 404):
        check(f"http {code} NOT retryable", not is_retryable_http(code))
    check("timeout retryable", is_retryable_exception(TimeoutError("timed out")))
    check("connection error retryable", is_retryable_exception(ConnectionError("refused")))
    check("value error NOT retryable", not is_retryable_exception(ValueError("bad key")))
    check("http 429 exception retryable", is_retryable_exception(http_error(429)))
    check("http 401 exception NOT retryable", not is_retryable_exception(http_error(401)))

    # ── Backoff math ──────────────────────────────────────────────────
    samples = [compute_backoff(a, 1.0) for a in range(5)]
    check("backoff zero jitter possible", all(0 <= s <= 2 ** a for a, s in enumerate(samples)))
    check("backoff capped", compute_backoff(10, 1.0, max_delay=30.0) <= 30.0)

    # ── run_with_retries ──────────────────────────────────────────────
    calls = []
    def flaky_twice():
        calls.append(1)
        if len(calls) < 3:
            raise TimeoutError("timed out")
        return "ok"
    with patch("rex.retry.sleep_with_abort", return_value=True):
        check("retries then succeeds", run_with_retries(flaky_twice, max_retries=3, base_delay=0) == "ok")
        check("two transient failures retried", len(calls) == 3)

    calls.clear()
    def always_401():
        calls.append(1)
        raise http_error(401)
    try:
        run_with_retries(always_401, max_retries=5, base_delay=0)
        check("401 raises immediately", False)
    except Exception:
        check("401 raises immediately", True)
    check("401 not retried", len(calls) == 1)

    calls.clear()
    def always_503():
        calls.append(1)
        raise http_error(503)
    try:
        with patch("rex.retry.sleep_with_abort", return_value=True):
            run_with_retries(always_503, max_retries=2, base_delay=0)
        check("exhaustion raises", False)
    except Exception:
        check("exhaustion raises", True)
    check("exhausted after max_retries+1 attempts", len(calls) == 3)

    calls.clear()
    def aborting_op():
        calls.append(1)
        raise TimeoutError("timed out")
    try:
        with patch("rex.retry.sleep_with_abort", return_value=False):
            run_with_retries(aborting_op, max_retries=5, base_delay=0)
        check("abort stops retries", False)
    except Exception:
        check("abort stops retries", True)
    check("abort = single attempt", len(calls) == 1)

    # ── Usage parsing ─────────────────────────────────────────────────
    u = parse_usage({"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})
    check("usage full response", u == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
    u = parse_usage({"prompt_tokens": 7})
    check("usage raw dict", u and u["prompt_tokens"] == 7 and u["total_tokens"] == 7)
    u = parse_usage({"input_tokens": 3, "output_tokens": 4})
    check("usage anthropic style", u == {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7})
    check("usage missing -> None", parse_usage({"choices": []}) is None)
    check("usage zero -> None", parse_usage({"usage": {"prompt_tokens": 0}}) is None)

    # ── Usage class on LLMResponse ────────────────────────────────────
    resp = LLMResponse("hi", usage=Usage(1, 2, 3))
    check("llm response usage", resp.usage.to_dict() == {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3})
    check("llm response usage None default", LLMResponse("x").usage is None)
    check("usage from_dict None", Usage.from_dict(None) is None)

    print("\nRetry checks PASS")


if __name__ == "__main__":
    main()
