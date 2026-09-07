"""Self-check for Rex Desktop: settings API contract, .env key vault,
config round-trip, token auth, and static serving. Run: python test_desktop.py"""

import json
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rex.desktop import settings_api
from rex.config import ENV_FILE, load_config, save_config


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


def main():
    import tempfile
    orig_config = load_config()
    try:
        with tempfile.TemporaryDirectory() as td:
            run_checks(Path(td))
    finally:
        save_config(orig_config)  # restore real config.json


def run_checks(tmp: Path):
    # ── settings contract ────────────────────────────────────────
    snap = settings_api.settings_get()
    check("settings_get ok", snap.get("ok") is True)
    s = snap["settings"]
    check("settings keys", all(k in s for k in (
        "default_mode", "token_budget", "max_steps", "streaming",
        "anti_slop", "terminal_timeout", "max_history")))
    check("default_mode valid", s["default_mode"] in ("plan", "build"))

    # round-trip: update then read back
    r = settings_api.settings_update({"token_budget": "12345", "streaming": "off"})
    check("settings_update ok", r.get("ok") is True)
    s2 = settings_api.settings_get()["settings"]
    check("token_budget round-trip", s2["token_budget"] == 12345)
    check("streaming round-trip", s2["streaming"] == "off")
    check("stream_enabled bool in config", load_config()["stream_enabled"] is False)

    r = settings_api.settings_update({"token_budget": "-5"})
    check("negative budget rejected", r.get("ok") is False)
    r = settings_api.settings_update({"default_mode": "yolo"})
    check("invalid mode rejected", r.get("ok") is False)


    # ── providers contract ───────────────────────────────────────
    pl = settings_api.providers_list()
    check("providers_list ok", pl.get("ok") is True)
    check("providers nonempty", len(pl["providers"]) >= 1)
    check("active listed", pl.get("active") == load_config().get("active_provider"))
    first = pl["providers"][0]
    check("provider fields", all(k in first for k in (
        "id", "name", "base_url", "model", "api_key_env", "has_key", "available_models")))
    check("no api key material in payload", "api_key" not in first)

    # activate round-trip
    other = next((p["id"] for p in pl["providers"] if p["id"] != pl["active"]), None)
    if other:
        r = settings_api.provider_mutate({"action": "activate", "id": other})
        check("activate ok", r.get("ok") is True)
        check("active switched", load_config()["active_provider"] == other)
        r = settings_api.provider_mutate({"action": "activate", "id": pl["active"]})
        check("activate back", r.get("ok") is True)

    # update rejects unknown provider
    r = settings_api.provider_mutate({"action": "update", "id": "nope", "data": {}})
    check("unknown provider rejected", r.get("ok") is False)

    # add + delete round-trip
    r = settings_api.provider_mutate({"action": "add", "id": "testprov",
                                      "data": {"name": "Test", "base_url": "https://x/v1", "model": "m1"}})
    check("add provider", r.get("ok") is True)
    cfg = load_config()
    check("added provider persisted", "testprov" in cfg["providers"])
    check("added api_key_env default", cfg["providers"]["testprov"]["api_key_env"] == "TESTPROV_API_KEY")
    r = settings_api.provider_mutate({"action": "delete", "id": "testprov"})
    check("delete provider", r.get("ok") is True)
    check("deleted gone", "testprov" not in load_config()["providers"])
    r = settings_api.provider_mutate({"action": "delete", "id": load_config()["active_provider"]})
    check("cannot delete active", r.get("ok") is False)
    r = settings_api.provider_mutate({"action": "bogus"})
    check("bad action rejected", r.get("ok") is False)

    # ── .env key vault ───────────────────────────────────────────
    fake_env = tmp / ".env"
    fake_env.write_text("# vault\nEXISTING_KEY=old\n", encoding="utf-8")
    saved_file = settings_api.ENV_FILE
    settings_api.ENV_FILE = fake_env
    try:
        r = settings_api.key_write({"id": "x", "api_key_env": "REX_TEST_KEY", "api_key": "sk-secret"})
        check("key_write ok", r.get("ok") is True)
        text = fake_env.read_text(encoding="utf-8")
        check("key appended to vault", "REX_TEST_KEY=sk-secret" in text)
        check("comment preserved", "# vault" in text)
        check("existing key preserved", "EXISTING_KEY=old" in text)
        check("live env var set", os.environ.get("REX_TEST_KEY") == "sk-secret")
        r = settings_api.key_write({"id": "x", "api_key_env": "REX_TEST_KEY", "api_key": "sk-rotate"})
        check("key rotated", "REX_TEST_KEY=sk-rotate" in fake_env.read_text(encoding="utf-8"))
        check("single entry after rotate", fake_env.read_text(encoding="utf-8").count("REX_TEST_KEY=") == 1)
        r = settings_api.key_write({"id": "x", "api_key_env": "REX_TEST_KEY"})
        check("missing key rejected", r.get("ok") is False)
        r = settings_api.key_write({"id": "x", "api_key_env": "bad-name", "api_key": "k"})
        check("bad env name rejected", r.get("ok") is False)
        check("no key material in config", "sk-secret" not in json.dumps(load_config()))
    finally:
        settings_api.ENV_FILE = saved_file
        os.environ.pop("REX_TEST_KEY", None)

    # provider update with api_key routes through the vault
    settings_api.provider_mutate({"action": "add", "id": "testprov",
                                  "data": {"name": "T", "base_url": "https://x/v1"}})
    settings_api.ENV_FILE = tmp / "env2"
    try:
        r = settings_api.provider_mutate({"action": "update", "id": "testprov",
                                          "data": {"api_key": "sk-vaulted", "model": "m2"}})
        check("update with key ok", r.get("ok") is True)
        check("key routed to vault", "TESTPROV_API_KEY=sk-vaulted" in (tmp / "env2").read_text(encoding="utf-8"))
        check("model persisted", load_config()["providers"]["testprov"]["model"] == "m2")
    finally:
        settings_api.ENV_FILE = saved_file
        os.environ.pop("TESTPROV_API_KEY", None)
        settings_api.provider_mutate({"action": "delete", "id": "testprov"})

    # ── onboarding contract ─────────────────────────────────────
    st = settings_api.onboarding_status()
    check("onboarding_status ok", st.get("ok") is True)
    check("onboarding fields", all(k in st for k in ("needed", "provider", "api_key_env", "model")))
    check("needed is bool", isinstance(st["needed"], bool))

    # ── live server: token auth + static + endpoints ────────────
    server_checks()


def server_checks():
    import secrets as _secrets
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    from rex.app_controller import ChatController
    from rex.desktop.server import DesktopHandler, DesktopHub, _usage_snapshot

    controller = ChatController()
    usage = _usage_snapshot(controller)
    check("usage contract", usage.get("ok") is True and "total_tokens" in usage and "cost_usd" in usage)

    real_hub = DesktopHub(controller)
    real_hub.attach_approval_provider()
    token = _secrets.token_hex(16)
    handler = type("T", (DesktopHandler,), {"hub": real_hub, "token": token})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:" + str(port)

    def get_status(path, tok=None):
        url = base + path
        if tok:
            url += ("&t=" + tok if "?" in path else "?t=" + tok)
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, ""

    def post_status(path, payload, tok=None):
        req = urllib.request.Request(
            base + path + ("?t=" + tok if tok else ""),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8") if exc.fp else ""

    try:
        code, _ = get_status("/api/settings")
        check("no token denied (403)", code == 403)
        code, _ = get_status("/api/settings", tok="deadbeef")
        check("wrong token denied (403)", code == 403)
        code, body = get_status("/api/settings", tok=token)
        check("settings endpoint ok", code == 200 and json.loads(body).get("ok") is True)
        code, body = get_status("/api/providers", tok=token)
        payload = json.loads(body)
        check("providers endpoint ok", code == 200 and payload.get("ok") is True)
        check("providers payload safe", all("api_key" not in p for p in payload.get("providers", [])))
        code, body = get_status("/api/state", tok=token)
        check("state endpoint ok", code == 200 and "mode" in json.loads(body))
        code, body = get_status("/api/onboarding", tok=token)
        check("onboarding endpoint ok", code == 200 and json.loads(body).get("ok") is True)
        code, body = get_status("/api/files", tok=token)
        check("files endpoint ok", code == 200 and isinstance(json.loads(body).get("files"), list))

        # ── desktop foundations endpoints (v0.3.3) ──────────────────
        code, body = get_status("/api/checkpoints", tok=token)
        payload = json.loads(body)
        check("checkpoints endpoint ok", code == 200 and isinstance(payload.get("checkpoints"), list))

        code, body = get_status("/api/todos", tok=token)
        payload = json.loads(body)
        check("todos endpoint ok", code == 200 and isinstance(payload.get("todos"), list)
              and isinstance(payload.get("summary"), str))

        code, body = get_status("/api/diff", tok=token)
        check("diff endpoint ok", code == 200 and "diff" in json.loads(body))

        code, body = get_status("/api/health", tok=token)
        payload = json.loads(body)
        check("health endpoint ok", code == 200 and isinstance(payload.get("results"), list)
              and isinstance(payload.get("all_ok"), bool))

        # export: mocked core (export_session writes files to disk — never in tests)
        import rex.export as export_mod
        orig_export = export_mod.export_session
        export_mod.export_session = lambda sid, fmt="md", out_dir=None: f"OK: workspace/exports/rex-test-session.{fmt}"
        try:
            code, body = get_status("/api/export?fmt=md", tok=token)
            payload = json.loads(body)
            check("export endpoint contract", code == 200 and payload.get("ok") is True
                  and "message" in payload)
        finally:
            export_mod.export_session = orig_export

        code, body = get_status("/api/stats", tok=token)
        check("stats endpoint ok", code == 200 and isinstance(json.loads(body).get("stats"), dict))

        # rollback endpoints: input validation must never reach the workspace
        code, body = post_status("/api/rewind", {"steps": "abc"}, tok=token)
        check("rewind rejects non-numeric steps (400)", code == 400)
        code, body = post_status("/api/rewind", {"steps": 0}, tok=token)
        check("rewind rejects steps<1 (400)", code == 400)
        code, body = post_status("/api/rewind", {"steps": 999}, tok=token)
        check("rewind rejects steps>100 (400)", code == 400)

        # rollback endpoints: mocked core (never mutates real checkpoints)
        import rex.checkpoints as checkpoints_mod
        orig_undo = checkpoints_mod.undo
        orig_redo = checkpoints_mod.redo
        orig_rewind = checkpoints_mod.rewind
        checkpoints_mod.undo = lambda: {"previous": "abc1234", "saved": "def5678"}
        checkpoints_mod.redo = lambda: {"restored": "def5678"}
        checkpoints_mod.rewind = lambda steps=1: {"restored": "abc1234", "saved": "def5678", "steps": steps}
        try:
            code, body = post_status("/api/rewind", {"steps": 3}, tok=token)
            payload = json.loads(body)
            check("rewind ok + echoes steps", code == 200 and payload.get("ok") is True
                  and payload.get("result", {}).get("steps") == 3)
            code, body = post_status("/api/undo", {}, tok=token)
            payload = json.loads(body)
            check("undo ok + result contract", code == 200 and payload.get("ok") is True
                  and "previous" in payload.get("result", {}))
            code, body = post_status("/api/redo", {}, tok=token)
            payload = json.loads(body)
            check("redo ok + result contract", code == 200 and payload.get("ok") is True
                  and "restored" in payload.get("result", {}))
        finally:
            checkpoints_mod.undo = orig_undo
            checkpoints_mod.redo = orig_redo
            checkpoints_mod.rewind = orig_rewind

        code, body = get_status("/", tok=token)
        check("index served", code == 200 and "<!doctype html" in body.lower())
        check("spa assets referenced", "app.js" in body and "app.css" in body)
        code, body = get_status("/app.js", tok=token)
        check("app.js served", code == 200 and "Rex Desktop" in body)
        code, body = get_status("/app.css", tok=token)
        check("app.css served", code == 200 and len(body) > 100)
        code, _ = get_status("/../cli.py", tok=token)
        check("traversal blocked", code in (301, 404, 403))
    finally:
        httpd.shutdown()
        httpd.server_close()


if __name__ == "__main__":
    main()

