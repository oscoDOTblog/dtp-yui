"""Job lifecycle helpers (delete + cascade, manual title edits)."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import collections as C
from .db import get_db
from .gap_insights import remove_job_from_gap_insights

logger = logging.getLogger(__name__)

MAX_MANUAL_TITLE_LENGTH = 160


def clean_manual_title(value: str | None) -> str:
    """Collapse whitespace and cap length for a human-entered title."""
    return " ".join((value or "").split())[:MAX_MANUAL_TITLE_LENGTH]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _role_gate_updates(job: dict, title: str) -> dict[str, Any]:
    """Re-run the SWE title gate for a new title.

    Only jobs still sitting on the gate (`new` / `wrong_role`) change status, so a
    correction can rescue a mis-parsed listing without discarding existing analysis
    or overriding the location gate.
    """
    from .intake.role_filter import assess_role_fit

    assessment = assess_role_fit(
        title=title,
        description=job.get("descriptionRaw") or "",
    )
    updates: dict[str, Any] = {"roleAssessment": assessment}
    status = (job.get("status") or "").strip()
    if assessment.get("roleEligible"):
        if status == "wrong_role":
            updates["status"] = "new"
    elif status == "new":
        updates["status"] = "wrong_role"
    return updates


def set_job_title(job_id: str, title: str | None) -> dict:
    """Apply a human-edited title. Survives re-ingest polls and re-analyze."""
    from .matching import is_placeholder_title

    db = get_db()
    job = db[C.JOBS].find_one({"_id": job_id})
    if not job:
        raise KeyError(f"job not found: {job_id}")

    cleaned = clean_manual_title(title)
    if not cleaned:
        raise ValueError("title is required")
    if is_placeholder_title(cleaned):
        raise ValueError(f"'{cleaned}' is a placeholder, not a job title")

    now = _now()
    updates: dict[str, Any] = {
        "title": cleaned,
        "titleSource": "manual",
        "titleEditedAt": now,
        "updatedAt": now,
    }
    # Keep the detected title once so the edit can be reverted later
    if job.get("titleSource") != "manual":
        updates["titleAuto"] = job.get("title") or ""
    updates.update(_role_gate_updates(job, cleaned))

    db[C.JOBS].update_one({"_id": job_id}, {"$set": updates})
    return db[C.JOBS].find_one({"_id": job_id})


def clear_job_title_override(job_id: str) -> dict:
    """Drop a manual title and fall back to the last detected one."""
    db = get_db()
    job = db[C.JOBS].find_one({"_id": job_id})
    if not job:
        raise KeyError(f"job not found: {job_id}")
    if job.get("titleSource") != "manual":
        return job

    detected = clean_manual_title(job.get("titleAuto")) or "Untitled"
    now = _now()
    updates: dict[str, Any] = {
        "title": detected,
        "titleEditedAt": now,
        "updatedAt": now,
    }
    updates.update(_role_gate_updates(job, detected))

    db[C.JOBS].update_one(
        {"_id": job_id},
        {"$set": updates, "$unset": {"titleSource": "", "titleAuto": ""}},
    )
    return db[C.JOBS].find_one({"_id": job_id})


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
