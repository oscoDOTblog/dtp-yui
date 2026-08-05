"""Background application package generation (survives browser navigation)."""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from . import collections as C
from .db import get_db
from .documents import generate_application_package

logger = logging.getLogger(__name__)

RUN_TYPE = "generatePackage"
STALE_AFTER = timedelta(minutes=45)

_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _is_stale(run: dict[str, Any] | None) -> bool:
    if not run or run.get("status") != "running":
        return False
    started = _parse_iso(run.get("startedAt"))
    if not started:
        return True
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - started > STALE_AFTER


def _patch_run(run_id: str, fields: dict[str, Any]) -> None:
    get_db()[C.SYSTEM_RUNS].update_one({"_id": run_id}, {"$set": fields})


def get_running_generate(job_id: str) -> dict[str, Any] | None:
    """Return the active generate run for a job, or mark stale runs failed."""
    db = get_db()
    run = db[C.SYSTEM_RUNS].find_one(
        {"type": RUN_TYPE, "jobId": job_id, "status": "running"},
        sort=[("startedAt", -1)],
    )
    if not run:
        return None
    if _is_stale(run):
        _patch_run(
            run["_id"],
            {
                "status": "failed",
                "finishedAt": _now(),
                "error": "Generate timed out (stale run)",
                "message": "Generate timed out — try again.",
            },
        )
        return None
    return run


def get_generate_status(
    job_id: str, run_id: str | None = None
) -> dict[str, Any] | None:
    db = get_db()
    if run_id:
        run = db[C.SYSTEM_RUNS].find_one(
            {"_id": run_id, "type": RUN_TYPE, "jobId": job_id}
        )
        if run and run.get("status") == "running" and _is_stale(run):
            _patch_run(
                run["_id"],
                {
                    "status": "failed",
                    "finishedAt": _now(),
                    "error": "Generate timed out (stale run)",
                    "message": "Generate timed out — try again.",
                },
            )
            return db[C.SYSTEM_RUNS].find_one({"_id": run_id})
        return run

    running = get_running_generate(job_id)
    if running:
        return running
    return db[C.SYSTEM_RUNS].find_one(
        {"type": RUN_TYPE, "jobId": job_id},
        sort=[("startedAt", -1)],
    )


def start_generate_async(job_id: str) -> dict[str, Any]:
    """Start package generation in a background thread (single-flight per job)."""
    db = get_db()
    job = db[C.JOBS].find_one({"_id": job_id})
    if not job:
        raise KeyError(f"job not found: {job_id}")

    match = db[C.JOB_MATCHES].find_one({"jobId": job_id})
    if not match:
        raise RuntimeError("Analyze the job before generating documents")

    with _lock:
        running = get_running_generate(job_id)
        if running:
            return {
                "accepted": False,
                "conflict": True,
                "runId": running.get("_id"),
                "status": "running",
                "jobId": job_id,
                "message": "Package generation already running for this job",
                "startedAt": running.get("startedAt"),
            }

        run_id = f"gen_{uuid.uuid4().hex[:16]}"
        db[C.SYSTEM_RUNS].insert_one(
            {
                "_id": run_id,
                "type": RUN_TYPE,
                "jobId": job_id,
                "status": "running",
                "startedAt": _now(),
                "finishedAt": None,
                "error": None,
                "message": "Generating application package…",
                "packageId": None,
                "folderName": None,
            }
        )

        def _worker() -> None:
            try:
                package = generate_application_package(job_id)
                _patch_run(
                    run_id,
                    {
                        "status": "completed",
                        "finishedAt": _now(),
                        "error": None,
                        "message": f"Package ready: {package.get('folderName')}",
                        "packageId": package.get("_id"),
                        "folderName": package.get("folderName"),
                        "pipeline": package.get("pipeline"),
                    },
                )
                logger.info("Background generate complete: %s → %s", job_id, run_id)
            except Exception as exc:
                logger.exception("background generate failed for %s", job_id)
                _patch_run(
                    run_id,
                    {
                        "status": "failed",
                        "finishedAt": _now(),
                        "error": str(exc)[:500],
                        "message": "Package generation failed",
                    },
                )

        thread = threading.Thread(
            target=_worker, name=f"generate-{job_id[:24]}", daemon=True
        )
        thread.start()
        return {
            "accepted": True,
            "conflict": False,
            "runId": run_id,
            "status": "running",
            "jobId": job_id,
            "message": "Package generation started",
            "startedAt": _now(),
        }


def public_generate_status(run: dict[str, Any] | None) -> dict[str, Any] | None:
    if not run:
        return None
    return {
        "runId": run.get("_id"),
        "jobId": run.get("jobId"),
        "status": run.get("status"),
        "startedAt": run.get("startedAt"),
        "finishedAt": run.get("finishedAt"),
        "message": run.get("message"),
        "error": run.get("error"),
        "packageId": run.get("packageId"),
        "folderName": run.get("folderName"),
        "pipeline": run.get("pipeline"),
    }
