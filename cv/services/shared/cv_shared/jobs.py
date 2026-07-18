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
