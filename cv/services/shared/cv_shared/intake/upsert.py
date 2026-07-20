"""Upsert normalized jobs into cv_jobs with dedupe."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .. import collections as C
from ..db import get_db

logger = logging.getLogger(__name__)


def upsert_normalized_job(normalized: dict[str, Any]) -> dict[str, Any]:
    """Insert or refresh a job. Returns {job, created, reason}."""
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    external_id = normalized.get("externalId")
    content_hash = normalized.get("contentHash")
    fingerprints = normalized.get("fingerprints") or {}

    existing = None
    reason = None
    if external_id:
        existing = db[C.JOBS].find_one({"externalId": external_id})
        if existing:
            reason = "externalId"
    if not existing and content_hash:
        existing = db[C.JOBS].find_one({"contentHash": content_hash})
        if existing:
            reason = "contentHash"
    if not existing and fingerprints.get("exact"):
        existing = db[C.JOBS].find_one({"fingerprints.exact": fingerprints["exact"]})
        if existing:
            reason = "fingerprintExact"
    if not existing and fingerprints.get("fuzzy"):
        # Fuzzy match only when company+title collide and one side has weak location
        existing = db[C.JOBS].find_one({"fingerprints.fuzzy": fingerprints["fuzzy"]})
        if existing:
            reason = "fingerprintFuzzy"

    if existing:
        updates = {
            "lastSeenAt": now,
            "locationAssessment": normalized.get("locationAssessment"),
            "discoveredBy": normalized.get("discoveredBy") or existing.get("discoveredBy"),
        }
        if normalized.get("canonicalApplyUrl"):
            updates["canonicalApplyUrl"] = normalized["canonicalApplyUrl"]
            updates["url"] = normalized.get("url") or normalized["canonicalApplyUrl"]
        if normalized.get("descriptionRaw") and len(normalized["descriptionRaw"]) > len(
            existing.get("descriptionRaw") or ""
        ):
            updates["descriptionRaw"] = normalized["descriptionRaw"]
            updates["contentHash"] = content_hash
        # Do not reopen out_of_area → analyzed; refresh status only if still new/out_of_area
        if existing.get("status") in (None, "new", "out_of_area"):
            updates["status"] = normalized.get("status") or existing.get("status")
        db[C.JOBS].update_one({"_id": existing["_id"]}, {"$set": updates})
        job = db[C.JOBS].find_one({"_id": existing["_id"]})
        return {"job": job, "created": False, "reason": reason or "existing"}

    job_id = f"job_{(external_id or content_hash or fingerprints.get('exact') or 'x')}"
    job_id = "job_" + "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in job_id[4:])[:40]
    if db[C.JOBS].find_one({"_id": job_id}):
        job_id = f"job_{(content_hash or 'x')[:16]}"

    doc = {
        "_id": job_id,
        "source": normalized.get("source") or "unknown",
        "sourceJobId": external_id,
        "url": normalized.get("url"),
        "sourceUrl": normalized.get("sourceUrl"),
        "canonicalApplyUrl": normalized.get("canonicalApplyUrl"),
        "title": normalized.get("title") or "Untitled",
        "company": normalized.get("company") or "Unknown",
        "location": normalized.get("location") or "",
        "workMode": normalized.get("workMode") or "unknown",
        "salary": normalized.get("salary"),
        "descriptionRaw": normalized.get("descriptionRaw") or "",
        "requiredSkills": normalized.get("requiredSkills") or [],
        "preferredSkills": normalized.get("preferredSkills") or [],
        "postedAt": normalized.get("postedAt"),
        "discoveredAt": normalized.get("firstSeenAt") or now,
        "firstSeenAt": normalized.get("firstSeenAt") or now,
        "lastSeenAt": now,
        "status": normalized.get("status") or "new",
        "contentHash": content_hash,
        "fingerprints": fingerprints,
        "discoveredBy": normalized.get("discoveredBy"),
        "locationAssessment": normalized.get("locationAssessment"),
    }
    if external_id:
        doc["externalId"] = external_id
    db[C.JOBS].insert_one(doc)
    return {"job": doc, "created": True, "reason": "inserted"}
