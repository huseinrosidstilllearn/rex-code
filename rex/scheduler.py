"""
rex.scheduler
Cron-like scheduler for automated Rex Code jobs.
Runs in the same process as the FastAPI server (single-threaded background loop).
"""

import json
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from rex.config import load_config, normalize_config, PROJECT_ROOT
from rex.core import RexAgent
from rex.logging_setup import log

# Job execution history storage
SCHEDULER_LOG_DIR = PROJECT_ROOT / "logs"
SCHEDULER_LOG_FILE = SCHEDULER_LOG_DIR / "scheduler.log"
SCHEDULER_HISTORY_FILE = SCHEDULER_LOG_DIR / "jobs_history.json"

# Max history entries per job
MAX_HISTORY_PER_JOB = 50
def _cron_match(cron_expr: str, now: datetime) -> bool:
    """
    Simple 5-field cron matcher (minute hour day month weekday).
    Supports *, comma lists, ranges, and step values (e.g., */5).
    Does NOT support month/day names, @yearly, @monthly, etc.
    """
    try:
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            return False

        minute_s, hour_s, day_s, month_s, weekday_s = parts

        def match_field(field: str, value: int, max_val: int) -> bool:
            if field == "*":
                return True
            # Handle step values: */5, 1-10/2, etc.
            for part in field.split(","):
                if "/" in part:
                    base, step_s = part.split("/", 1)
                    try:
                        step = int(step_s)
                    except ValueError:
                        continue
                    if base == "*":
                        if value % step == 0:
                            return True
                    elif "-" in base:
                        start_s, end_s = base.split("-", 1)
                        try:
                            start = int(start_s)
                            end = int(end_s)
                            # inclusive range, stepped: start, start+step, ...
                            if start <= value <= end and (value - start) % step == 0:
                                return True
                        except ValueError:
                            continue
                elif "-" in part:
                    start_s, end_s = part.split("-", 1)
                    try:
                        start = int(start_s)
                        end = int(end_s)
                        if start <= value <= end:
                            return True
                    except ValueError:
                        continue
                else:
                    try:
                        if int(part) == value:
                            return True
                    except ValueError:
                        continue
            return False

        # Weekday: cron uses 0=Sunday; Python's weekday() is Monday=0.
        # Convert so both ranges (1-5 = Mon-Fri in cron) and single values
        # match the user's intent. 7 is accepted as an alias of Sunday.
        cron_weekday = (now.weekday() + 1) % 7  # Monday=0 -> cron 1 ... Sunday=6 -> cron 0
        return (
            match_field(minute_s, now.minute, 59)
            and match_field(hour_s, now.hour, 23)
            and match_field(day_s, now.day, 31)
            and match_field(month_s, now.month, 12)
            and (
                match_field(weekday_s, cron_weekday, 6)
                or (cron_weekday == 0 and match_field(weekday_s, 7, 7))
            )
        )
    except Exception:
        return False


def _append_history(job_id: str, entry: Dict[str, Any]) -> None:
    """Append execution record to jobs_history.json (atomic write)."""
    SCHEDULER_LOG_DIR.mkdir(parents=True, exist_ok=True)
    history: Dict[str, List[Dict[str, Any]]] = {}
    if SCHEDULER_HISTORY_FILE.exists():
        try:
            history = json.loads(SCHEDULER_HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            history = {}
    job_history = history.get(job_id, [])
    job_history.insert(0, entry)  # newest first
    if len(job_history) > MAX_HISTORY_PER_JOB:
        job_history = job_history[:MAX_HISTORY_PER_JOB]
    history[job_id] = job_history
    # Atomic write
    tmp = SCHEDULER_HISTORY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SCHEDULER_HISTORY_FILE)


def _log(msg: str) -> None:
    """Write to scheduler log file (append) and stdout."""
    SCHEDULER_LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}\n"
    try:
        with open(SCHEDULER_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
    print(line.strip())
class JobScheduler:
    """Background scheduler that checks cron jobs every minute."""

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_run: Dict[str, datetime] = {}  # job_id -> last run minute

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="rex-scheduler")
        self._thread.start()
        _log("Scheduler started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        _log("Scheduler stopped")

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._check_jobs()
            except Exception as exc:
                _log(f"Scheduler error: {exc}")
            # Sleep in small chunks to allow fast shutdown
            for _ in range(60):
                if self._stop.is_set():
                    break
                time.sleep(1)
    def _check_jobs(self) -> None:
        cfg = normalize_config(load_config())
        scheduler_cfg = cfg.get("scheduler", {})
        if not scheduler_cfg.get("enabled", True):
            return

        jobs = scheduler_cfg.get("jobs", [])
        if not jobs:
            return

        now = datetime.now()
        minute_key = now.replace(second=0, microsecond=0)

        for job in jobs:
            if not job.get("enabled", True):
                continue
            job_id = job["id"]
            cron = job["cron"]

            if not _cron_match(cron, now):
                continue

            # Prevent duplicate runs within the same minute
            last = self._last_run.get(job_id)
            if last == minute_key:
                continue

            # Check for overlap: if previous run still in progress (naive check via lock file)
            lock_file = SCHEDULER_LOG_DIR / f".job_{job_id}.lock"
            if lock_file.exists():
                try:
                    lock_age = time.time() - lock_file.stat().st_mtime
                    if lock_age < 300:  # 5 min max run time
                        _log(f"Job {job_id} skipped (previous run still active)")
                        continue
                except Exception:
                    pass

            self._last_run[job_id] = minute_key
            self._execute_job(job, lock_file)

    def _execute_job(self, job: Dict[str, Any], lock_file: Path) -> None:
        job_id = job["id"]
        prompt = job["prompt"]
        mode = job["mode"]

        _log(f"Job {job_id} starting (mode={mode})")
        start_time = time.time()

        # Create lock
        try:
            lock_file.write_text(str(datetime.now().isoformat()), encoding="utf-8")
        except Exception:
            pass

        entry = {
            "started_at": datetime.now().isoformat(),
            "mode": mode,
            "prompt": prompt[:200],
            "status": "running",
        }

        try:
            # Switch mode if needed
            from rex.config import get_active_mode, set_active_mode
            current_mode = get_active_mode()
            if current_mode != mode:
                set_active_mode(mode)

            # Run agent in a dedicated session
            session_id = f"job-{job_id}-{int(start_time)}"
            agent = RexAgent(session_id=session_id)
            result = agent.run(prompt)

            duration = time.time() - start_time
            entry.update({
                "status": "success",
                "finished_at": datetime.now().isoformat(),
                "duration_sec": round(duration, 2),
                "result_preview": str(result)[:500],
            })
            _log(f"Job {job_id} completed in {duration:.1f}s")

        except Exception as exc:
            duration = time.time() - start_time
            entry.update({
                "status": "error",
                "finished_at": datetime.now().isoformat(),
                "duration_sec": round(duration, 2),
                "error": str(exc),
            })
            _log(f"Job {job_id} failed after {duration:.1f}s: {exc}")

        finally:
            # Remove lock
            try:
                lock_file.unlink(missing_ok=True)
            except Exception:
                pass
            _append_history(job_id, entry)

    def trigger_job(self, job_id: str) -> Dict[str, Any]:
        """Manually trigger a job by ID (bypasses cron check)."""
        cfg = normalize_config(load_config())
        jobs = cfg.get("scheduler", {}).get("jobs", [])
        job = next((j for j in jobs if j["id"] == job_id), None)
        if not job:
            return {"ok": False, "error": f"Job '{job_id}' not found"}

        lock_file = SCHEDULER_LOG_DIR / f".job_{job_id}.lock"
        # Run in background thread
        threading.Thread(
            target=self._execute_job,
            args=(job, lock_file),
            daemon=True,
            name=f"rex-job-{job_id}",
        ).start()
        return {"ok": True, "job_id": job_id, "status": "started"}

    def get_job_status(self) -> List[Dict[str, Any]]:
        """Return current status of all jobs including history."""
        cfg = normalize_config(load_config())
        jobs = cfg.get("scheduler", {}).get("jobs", [])
        history: Dict[str, List[Dict[str, Any]]] = {}
        if SCHEDULER_HISTORY_FILE.exists():
            try:
                history = json.loads(SCHEDULER_HISTORY_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass

        result = []
        for job in jobs:
            job_id = job["id"]
            hist = history.get(job_id, [])
            last_run = hist[0] if hist else None
            result.append({
                "id": job_id,
                "cron": job["cron"],
                "prompt": job["prompt"],
                "mode": job["mode"],
                "enabled": job.get("enabled", True),
                "last_run": last_run,
                "history": hist[:10],  # recent 10
            })
        return result


# Global singleton
_scheduler: Optional[JobScheduler] = None


def get_scheduler() -> JobScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = JobScheduler()
    return _scheduler
