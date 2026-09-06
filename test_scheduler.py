"""Self-check the scheduler: cron semantics + CLI contract. Run: python test_scheduler.py"""

import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rex.scheduler as scheduler
from rex.scheduler import JobScheduler, _append_history, _cron_match


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


def main():
    tmp = Path(__file__).resolve().parent / "logs"
    tmp.mkdir(exist_ok=True)

    # ── Cron semantics. Weekday follows real cron: 0=Sunday .. 6=Saturday
    #    (7 also accepted as Sunday). 2026-09-06 is a Sunday, 09-07 Monday,
    #    09-09 Wednesday, 09-12 Saturday.
    sun = datetime(2026, 9, 6, 9, 0)
    mon = datetime(2026, 9, 7, 9, 0)
    wed = datetime(2026, 9, 9, 9, 0)
    sat = datetime(2026, 9, 12, 9, 0)

    check("1-5 matches Monday (cron Mon-Fri)", _cron_match("0 9 * * 1-5", mon))
    check("1-5 matches Wednesday", _cron_match("0 9 * * 1-5", wed))
    check("1-5 rejects Sunday", not _cron_match("0 9 * * 1-5", sun))
    check("1-5 rejects Saturday", not _cron_match("0 9 * * 1-5", sat))
    check("single 0 matches Sunday", _cron_match("0 9 * * 0", sun))
    check("single 7 matches Sunday (alias)", _cron_match("0 9 * * 7", sun))
    check("single 6 matches Saturday", _cron_match("0 9 * * 6", sat))
    check("single 6 rejects Sunday", not _cron_match("0 9 * * 6", sun))
    check("*/15 step hits :00", _cron_match("*/15 * * * *", sun.replace(minute=0)))
    check("*/15 step hits :15", _cron_match("*/15 * * * *", sun.replace(minute=15)))
    check("*/15 step skips :14", not _cron_match("*/15 * * * *", sun.replace(minute=14)))
    check("nightly 22:00 default job matches", _cron_match("0 22 * * *", sun.replace(hour=22)))
    check("hour mismatch rejected", not _cron_match("30 22 * * *", sun))
    check("invalid cron is never-true, not crash", not _cron_match("nonsense", sun))

    # ── Row contract: every key the CLI table reads must exist.
    fake_cfg = {"scheduler": {"enabled": True, "jobs": [{
        "id": "t", "cron": "0 22 * * *", "prompt": "p", "mode": "build", "enabled": True}]}}
    with patch.object(scheduler, "normalize_config", return_value=fake_cfg), \
         patch.object(scheduler, "SCHEDULER_HISTORY_FILE", tmp / "jobs_history.json"):
        rows = JobScheduler().get_job_status()
        required = {"id", "cron", "prompt", "mode", "enabled", "last_run", "history"}
        check("get_job_status rows carry all CLI keys", rows and required <= set(rows[0]))

        # ── History: newest-first, capped at MAX_HISTORY_PER_JOB.
        hist_file = tmp / "jobs_history.json"
        if hist_file.exists():
            hist_file.unlink()
        for i in range(scheduler.MAX_HISTORY_PER_JOB + 5):
            _append_history("t", {"n": i})
        data = json.loads(hist_file.read_text(encoding="utf-8"))
        check("history capped at MAX_HISTORY_PER_JOB",
              len(data["t"]) == scheduler.MAX_HISTORY_PER_JOB)
        check("history newest-first", data["t"][0]["n"] == scheduler.MAX_HISTORY_PER_JOB + 4)

    # ── Minute dedup: same job never double-fires within one minute.
    sched = JobScheduler()
    minute = datetime(2026, 9, 6, 22, 0)
    job = {"id": "t", "cron": "0 22 * * *", "prompt": "p", "mode": "build", "enabled": True}
    executed = []
    with patch.object(scheduler, "normalize_config", return_value={
            "scheduler": {"enabled": True, "jobs": [job]}}), \
         patch.object(scheduler, "SCHEDULER_LOG_DIR", tmp), \
         patch.object(sched, "_execute_job", side_effect=lambda j, lock: executed.append(j["id"])):
        sched._check_jobs_at(minute) if hasattr(sched, "_check_jobs_at") else None
        # call the real _check_jobs with a pinned 'now'
        with patch.object(scheduler, "datetime", wraps=scheduler.datetime) as dt:
            dt.now.return_value = minute
            sched._check_jobs()
            check("job executed once on matching minute", len(executed) == 1)
            sched._check_jobs()
            check("same minute does not re-execute", len(executed) == 1)

    print("\nScheduler checks PASS")


if __name__ == "__main__":
    main()
