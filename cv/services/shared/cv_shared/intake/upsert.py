"""Upsert normalized jobs into cv_jobs with dedupe."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import collections as C
from ..db import get_db
from .role_filter import assess_role_fit

logger = logging.getLogger(__name__)

# Weak identity (company+title fingerprints) only merges when postings are this close.
# A later opening with the same title at the same company is a new job past this window.
DEFAULT_FUZZY_DEDUPE_WINDOW_DAYS = 30


def fuzzy_dedupe_window_days() -> int:
    try:
        return max(
            1,
            int(
                os.environ.get(
                    "INGEST_FUZZY_DEDUPE_DAYS", DEFAULT_FUZZY_DEDUPE_WINDOW_DAYS
                )
            ),
        )
    except ValueError:
        return DEFAULT_FUZZY_DEDUPE_WINDOW_DAYS


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        cleaned = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def job_posting_dt(doc: dict[str, Any] | None) -> datetime | None:
    """Best-effort posting time: postedAt → firstSeenAt → discoveredAt."""
    if not doc:
        return None
    for key in ("postedAt", "firstSeenAt", "discoveredAt"):
        dt = _parse_dt(doc.get(key))
        if dt:
            return dt
    return None


def postings_within_window(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
    *,
    window_days: int | None = None,
) -> bool:
    """True when both sides have dates and |delta| ≤ window, or a date is missing.

    Missing dates favor merge (legacy rows / sources without publishedAt) so we
    still catch same-day cross-board reposts. When both dates exist and they
    fall outside the window, treat as a separate opening.
    """
    days = window_days if window_days is not None else fuzzy_dedupe_window_days()
    a = job_posting_dt(left)
    b = job_posting_dt(right)
    if a is None or b is None:
        return True
    return abs(a - b) <= timedelta(days=days)


def fingerprint_stub(fingerprints: dict[str, Any] | None) -> str:
    fps = fingerprints or {}
    return str(fps.get("exact") or fps.get("fuzzy") or "")[:12]


def _find_fingerprint_match(
    db,
    field: str,
    value: str,
    *,
    incoming: dict[str, Any],
    reason: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Match company/title fingerprints only when postings are within the date window."""
    if not value:
        return None, None
    window = fuzzy_dedupe_window_days()
    # Prefer the most recently posted candidate among matches
    candidates = list(
        db[C.JOBS]
        .find({field: value})
        .sort([("postedAt", -1), ("firstSeenAt", -1), ("discoveredAt", -1)])
        .limit(25)
    )
    for existing in candidates:
        if postings_within_window(incoming, existing, window_days=window):
            return existing, reason
        logger.debug(
            "Skipping %s dedupe for job outside %s-day window (%s vs %s)",
            reason,
            window,
            job_posting_dt(incoming),
            job_posting_dt(existing),
        )
    return None, None


def _find_existing(
    db,
    *,
    external_id: str | None,
    content_hash: str | None,
    fingerprints: dict[str, Any],
    url_key: str | None,
    incoming: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """Locate a prior job across sources. Lookup order favors strongest identity.

    Strong keys (same board id / apply URL) merge without a date window.
    Fingerprint + contentHash require postings within the fuzzy window so a
    reopened role at the same company+title becomes a new job.
    """
    if external_id:
        existing = db[C.JOBS].find_one({"externalId": external_id})
        if existing:
            return existing, "externalId"
        # Seen before via a different board that still recorded this id
        existing = db[C.JOBS].find_one({"altExternalIds": external_id})
        if existing:
            return existing, "altExternalId"

    if url_key:
        existing = db[C.JOBS].find_one({"urlKey": url_key})
        if existing:
            return existing, "urlKey"

    if content_hash:
        existing = db[C.JOBS].find_one({"contentHash": content_hash})
        if existing and postings_within_window(incoming, existing):
            return existing, "contentHash"

    if fingerprints.get("exact"):
        hit, reason = _find_fingerprint_match(
            db,
            "fingerprints.exact",
            fingerprints["exact"],
            incoming=incoming,
            reason="fingerprintExact",
        )
        if hit:
            return hit, reason

    # Company + normalized title — primary cross-board repost catch
    if fingerprints.get("fuzzy"):
        hit, reason = _find_fingerprint_match(
            db,
            "fingerprints.fuzzy",
            fingerprints["fuzzy"],
            incoming=incoming,
            reason="fingerprintFuzzy",
        )
        if hit:
            return hit, reason

    return None, None


def upsert_normalized_job(normalized: dict[str, Any]) -> dict[str, Any]:
    """Insert or refresh a job. Returns {job, created, reason}.

    Cross-source reposts merge onto one row when externalId / apply URL / content /
    company+title match and (for weak keys) postings are within 30 days.
    """
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    external_id = normalized.get("externalId")
    content_hash = normalized.get("contentHash")
    fingerprints = normalized.get("fingerprints") or {}
    url_key = normalized.get("urlKey")
    source = (normalized.get("source") or "unknown").strip()

    existing, reason = _find_existing(
        db,
        external_id=external_id,
        content_hash=content_hash,
        fingerprints=fingerprints,
        url_key=url_key,
        incoming=normalized,
    )

    if existing:
        title_is_manual = existing.get("titleSource") == "manual"
        if title_is_manual:
            # The source title would re-gate the listing; grade the human title
            role_assessment = assess_role_fit(
                title=existing.get("title") or "",
                description=normalized.get("descriptionRaw")
                or existing.get("descriptionRaw")
                or "",
            )
        else:
            role_assessment = normalized.get("roleAssessment")
        updates: dict[str, Any] = {
            "lastSeenAt": now,
            "locationAssessment": normalized.get("locationAssessment"),
            "roleAssessment": role_assessment,
            "discoveredBy": normalized.get("discoveredBy")
            or existing.get("discoveredBy"),
        }
        # Always refresh URLs when present; never clear existing URL fields
        if normalized.get("canonicalApplyUrl"):
            updates["canonicalApplyUrl"] = normalized["canonicalApplyUrl"]
        if normalized.get("sourceUrl"):
            updates["sourceUrl"] = normalized["sourceUrl"]
        new_url = (
            normalized.get("url")
            or normalized.get("canonicalApplyUrl")
            or normalized.get("sourceUrl")
        )
        if new_url:
            updates["url"] = new_url
        if url_key and not existing.get("urlKey"):
            updates["urlKey"] = url_key
        if normalized.get("fetchStatus"):
            updates["fetchStatus"] = normalized["fetchStatus"]
        if normalized.get("title") and normalized["title"] not in ("Untitled",):
            if title_is_manual:
                # Keep the human title; track the newest detected one for revert
                updates["titleAuto"] = normalized["title"]
            else:
                updates["title"] = normalized["title"]
        if normalized.get("company") and normalized["company"] not in ("Unknown",):
            updates["company"] = normalized["company"]
        if normalized.get("location"):
            updates["location"] = normalized["location"]
        if fingerprints:
            # Refresh for improved company/title normalizers
            updates["fingerprints"] = fingerprints
        # Keep earliest postedAt; set if missing
        if normalized.get("postedAt") and not existing.get("postedAt"):
            updates["postedAt"] = normalized["postedAt"]
        if normalized.get("descriptionRaw") and len(normalized["descriptionRaw"]) > len(
            existing.get("descriptionRaw") or ""
        ):
            updates["descriptionRaw"] = normalized["descriptionRaw"]
            updates["contentHash"] = content_hash
        incoming_md = (normalized.get("descriptionMarkdown") or "").strip()
        if incoming_md and len(incoming_md) > len(
            existing.get("descriptionMarkdown") or ""
        ):
            updates["descriptionMarkdown"] = incoming_md
        if existing.get("status") in (None, "new", "out_of_area", "wrong_role"):
            next_status = normalized.get("status") or existing.get("status")
            if (
                title_is_manual
                and next_status == "wrong_role"
                and (role_assessment or {}).get("roleEligible")
            ):
                next_status = "new"
            updates["status"] = next_status

        set_ops: dict[str, Any] = {"$set": updates}
        add_sets: dict[str, Any] = {}
        if source:
            add_sets["sourcesSeen"] = source
        if external_id and external_id != existing.get("externalId"):
            add_sets["altExternalIds"] = external_id
        if add_sets:
            set_ops["$addToSet"] = add_sets

        db[C.JOBS].update_one({"_id": existing["_id"]}, set_ops)
        job = db[C.JOBS].find_one({"_id": existing["_id"]})
        return {"job": job, "created": False, "reason": reason or "existing"}

    job_id = f"job_{(external_id or content_hash or fingerprints.get('exact') or 'x')}"
    job_id = "job_" + "".join(
        ch if ch.isalnum() or ch == "_" else "_" for ch in job_id[4:]
    )[:40]
    if db[C.JOBS].find_one({"_id": job_id}):
        # Collision with an older outside-window opening — unique stamp.
        stamp = (str(normalized.get("postedAt") or now)[:10]).replace("-", "")
        job_id = (
            f"job_{(content_hash or fingerprint_stub(fingerprints) or 'x')[:12]}_{stamp}"
        )

    doc = {
        "_id": job_id,
        "source": source or "unknown",
        "sourceJobId": external_id,
        "url": normalized.get("url"),
        "sourceUrl": normalized.get("sourceUrl"),
        "canonicalApplyUrl": normalized.get("canonicalApplyUrl"),
        "urlKey": url_key,
        "title": normalized.get("title") or "Untitled",
        "company": normalized.get("company") or "Unknown",
        "location": normalized.get("location") or "",
        "workMode": normalized.get("workMode") or "unknown",
        "salary": normalized.get("salary"),
        "descriptionRaw": normalized.get("descriptionRaw") or "",
        "descriptionMarkdown": (normalized.get("descriptionMarkdown") or "").strip()
        or None,
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
        "roleAssessment": normalized.get("roleAssessment"),
        "fetchStatus": normalized.get("fetchStatus"),
        "sourcesSeen": [source] if source else [],
        "altExternalIds": [],
    }
    if external_id:
        doc["externalId"] = external_id
    # Prefer resolved apply URL
    doc["url"] = (
        normalized.get("url")
        or normalized.get("canonicalApplyUrl")
        or normalized.get("sourceUrl")
    )
    db[C.JOBS].insert_one(doc)
    return {"job": doc, "created": True, "reason": "inserted"}
