"""Job lifecycle helpers (delete + cascade)."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from . import collections as C
from .db import get_db
from .gap_insights import remove_job_from_gap_insights

logger = logging.getLogger(__name__)


def delete_job(job_id: str) -> dict:
    """Delete a job and all associated Mongo docs + generated package folder."""
    db = get_db()
    job = db[C.JOBS].find_one({"_id": job_id})
    if not job:
        raise KeyError(f"job not found: {job_id}")

    match = db[C.JOB_MATCHES].find_one({"jobId": job_id})
    packages = list(db[C.APPLICATION_PACKAGES].find({"jobId": job_id}))

    # Reverse gap aggregates while match still exists
    try:
        remove_job_from_gap_insights(job_id, match)
    except Exception:
        logger.exception("gap insights cleanup failed for job %s", job_id)

    counts = {
        "job": db[C.JOBS].delete_one({"_id": job_id}).deleted_count,
        "matches": db[C.JOB_MATCHES].delete_many({"jobId": job_id}).deleted_count,
        "decisions": db[C.USER_DECISIONS].delete_many({"jobId": job_id}).deleted_count,
        "applications": db[C.APPLICATIONS].delete_many({"jobId": job_id}).deleted_count,
        "packages": db[C.APPLICATION_PACKAGES].delete_many({"jobId": job_id}).deleted_count,
        "documents": db[C.DOCUMENTS].delete_many({"jobId": job_id}).deleted_count,
        "systemRuns": db[C.SYSTEM_RUNS].delete_many({"jobId": job_id}).deleted_count,
        "foldersRemoved": 0,
    }

    for pkg in packages:
        folder = pkg.get("folder")
        if not folder:
            continue
        path = Path(folder)
        try:
            if path.is_dir():
                shutil.rmtree(path)
                counts["foldersRemoved"] += 1
        except OSError:
            logger.exception("failed to remove package folder %s", folder)

    return {
        "jobId": job_id,
        "title": job.get("title"),
        "company": job.get("company"),
        "deleted": counts,
    }


def delete_jobs(job_ids: list[str]) -> dict:
    """Cascade-delete many jobs. Continues on missing ids; reports per-id results."""
    deleted: list[dict] = []
    missing: list[str] = []
    errors: list[dict] = []

    seen: set[str] = set()
    for raw_id in job_ids:
        job_id = (raw_id or "").strip()
        if not job_id or job_id in seen:
            continue
        seen.add(job_id)
        try:
            deleted.append(delete_job(job_id))
        except KeyError:
            missing.append(job_id)
        except Exception as exc:
            logger.exception("bulk delete failed for %s", job_id)
            errors.append({"jobId": job_id, "error": str(exc)})

    return {
        "requested": len(seen),
        "deletedCount": len(deleted),
        "deleted": deleted,
        "missing": missing,
        "errors": errors,
    }
