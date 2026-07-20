"""Normalize raw intake records into a common job shape."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from .fingerprints import build_fingerprints
from .location import assess_location


def _content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def normalize_raw_job(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert a source-specific raw job into the shared normalized shape."""
    now = datetime.now(timezone.utc).isoformat()
    title = (raw.get("title") or "Untitled").strip()
    company = (raw.get("company") or "Unknown").strip()
    location = (raw.get("location") or "").strip()
    description = (raw.get("descriptionText") or raw.get("descriptionRaw") or "").strip()
    source = (raw.get("source") or "unknown").strip()
    source_url = (raw.get("sourceUrl") or raw.get("url") or "").strip() or None
    apply_url = (raw.get("canonicalApplyUrl") or source_url or "").strip() or None
    external_id = (raw.get("externalId") or "").strip() or None
    discovered_by = raw.get("discoveredBy") or {"source": source}
    alert_location = None
    if isinstance(discovered_by, dict):
        alert_location = discovered_by.get("alertLocation")

    location_assessment = raw.get("locationAssessment") or assess_location(
        location=location,
        title=title,
        description=description,
        alert_location=alert_location,
        work_mode_hint=raw.get("workMode") or raw.get("remoteType"),
    )

    work_mode = raw.get("workMode") or location_assessment.get("workArrangement") or "unknown"
    fingerprints = build_fingerprints(company, title, location)
    digest = _content_hash(description or f"{company}|{title}|{source_url or ''}")

    status = "new"
    if not location_assessment.get("bayAreaEligible"):
        status = "out_of_area"

    return {
        "externalId": external_id,
        "source": source,
        "sourceUrl": source_url,
        "canonicalApplyUrl": apply_url,
        "url": apply_url or source_url,
        "fetchStatus": raw.get("fetchStatus"),
        "title": title,
        "company": company,
        "location": location,
        "workMode": work_mode,
        "descriptionRaw": description,
        "postedAt": raw.get("postedAt"),
        "discoveredBy": discovered_by,
        "locationAssessment": location_assessment,
        "fingerprints": fingerprints,
        "contentHash": digest,
        "firstSeenAt": raw.get("firstSeenAt") or now,
        "lastSeenAt": now,
        "status": status,
        "salary": raw.get("salary"),
        "requiredSkills": raw.get("requiredSkills") or [],
        "preferredSkills": raw.get("preferredSkills") or [],
    }
