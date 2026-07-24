"""Manual URL intake queue (Analyze → pending → ingest drain)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from pymongo import ReturnDocument

from .. import collections as C
from ..db import get_db

REUSABLE_STATUSES = ("pending", "processing", "needsPaste", "failed")
DELETABLE_STATUSES = ("pending", "failed", "needsPaste", "done")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_url(url: str) -> str:
    """Trim and lightly normalize a job URL for dedupe."""
    raw = (url or "").strip()
    if not raw:
        return ""
    # Allow bare domains pasted without scheme
    if not re.match(r"^https?://", raw, flags=re.I):
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    if not parsed.netloc:
        return ""
    # Drop fragment; keep query (ATS ids often live there)
    path = parsed.path or ""
    if path.endswith("/") and path != "/":
        path = path.rstrip("/")
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}{query}"


def _parse_url_list(urls: list[str] | str | None) -> list[str]:
    if urls is None:
        return []
    if isinstance(urls, str):
        lines = urls.replace(",", "\n").splitlines()
    else:
        lines = []
        for item in urls:
            if not item:
                continue
            lines.extend(str(item).replace(",", "\n").splitlines())
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        normalized = normalize_url(line)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def enqueue_urls(
    urls: list[str] | str | None,
    *,
    description_raw: str | None = None,
) -> list[dict[str, Any]]:
    """Insert or reuse pending queue rows. Returns the affected items."""
    url_list = _parse_url_list(urls)
    if not url_list:
        raise ValueError("Provide at least one job URL")

    paste = (description_raw or "").strip() or None
    # Paste attaches to the first URL only (Analyze single-paste UX)
    db = get_db()
    now = _now()
    items: list[dict[str, Any]] = []

    for idx, url in enumerate(url_list):
        existing = db[C.INTAKE_QUEUE].find_one(
            {"url": url, "status": {"$in": list(REUSABLE_STATUSES)}},
            sort=[("createdAt", -1)],
        )
        if existing:
            updates: dict[str, Any] = {"updatedAt": now}
            if existing.get("status") in ("needsPaste", "failed"):
                updates["status"] = "pending"
                updates["error"] = None
                updates["processedAt"] = None
            if paste and idx == 0:
                updates["descriptionRaw"] = paste
                updates["status"] = "pending"
                updates["error"] = None
            if len(updates) > 1 or updates.get("status"):
                db[C.INTAKE_QUEUE].update_one({"_id": existing["_id"]}, {"$set": updates})
                existing = {**existing, **updates}
            items.append(existing)
            continue

        doc = {
            "_id": f"iq_{uuid.uuid4().hex[:16]}",
            "url": url,
            "descriptionRaw": paste if idx == 0 else None,
            "status": "pending",
            "error": None,
            "jobId": None,
            "fetchStatus": None,
            "createdAt": now,
            "updatedAt": now,
            "processedAt": None,
        }
        db[C.INTAKE_QUEUE].insert_one(doc)
        items.append(doc)

    return items


def list_queue(*, limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 50), 200))
    return list(
        get_db()[C.INTAKE_QUEUE].find({}, sort=[("createdAt", -1)], limit=limit)
    )


def get_queue_item(item_id: str) -> dict[str, Any] | None:
    return get_db()[C.INTAKE_QUEUE].find_one({"_id": item_id})


def patch_queue_item(
    item_id: str,
    *,
    description_raw: str | None = None,
) -> dict[str, Any]:
    """Attach pasted description; move needsPaste/failed back to pending."""
    db = get_db()
    doc = db[C.INTAKE_QUEUE].find_one({"_id": item_id})
    if not doc:
        raise KeyError(item_id)
    if doc.get("status") == "processing":
        raise ValueError("Cannot edit an item that is currently processing")
    if doc.get("status") == "done":
        raise ValueError("Item already completed")

    paste = (description_raw or "").strip()
    if not paste:
        raise ValueError("descriptionRaw is required")

    now = _now()
    updated = db[C.INTAKE_QUEUE].find_one_and_update(
        {"_id": item_id},
        {
            "$set": {
                "descriptionRaw": paste,
                "status": "pending",
                "error": None,
                "fetchStatus": None,
                "updatedAt": now,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        raise KeyError(item_id)
    return updated


def delete_queue_item(item_id: str) -> bool:
    db = get_db()
    doc = db[C.INTAKE_QUEUE].find_one({"_id": item_id})
    if not doc:
        return False
    if doc.get("status") == "processing":
        raise ValueError("Cannot delete an item that is currently processing")
    if doc.get("status") not in DELETABLE_STATUSES:
        raise ValueError(f"Cannot delete item in status {doc.get('status')}")
    result = db[C.INTAKE_QUEUE].delete_one({"_id": item_id})
    return result.deleted_count > 0


def clear_queue() -> dict[str, int]:
    """Delete all queue rows except those currently processing."""
    db = get_db()
    skipped = db[C.INTAKE_QUEUE].count_documents({"status": "processing"})
    result = db[C.INTAKE_QUEUE].delete_many({"status": {"$ne": "processing"}})
    return {
        "deletedCount": int(result.deleted_count or 0),
        "skippedProcessing": int(skipped or 0),
    }


def reclaim_stuck_processing() -> int:
    """Move abandoned processing rows back to pending (crash recovery)."""
    result = get_db()[C.INTAKE_QUEUE].update_many(
        {"status": "processing"},
        {
            "$set": {
                "status": "pending",
                "updatedAt": _now(),
                "error": None,
            }
        },
    )
    return int(result.modified_count or 0)


def claim_pending(*, limit: int = 40) -> list[dict[str, Any]]:
    """Atomically claim up to ``limit`` pending rows for processing."""
    reclaim_stuck_processing()
    limit = max(1, min(int(limit or 40), 100))
    db = get_db()
    claimed: list[dict[str, Any]] = []
    now = _now()
    for _ in range(limit):
        doc = db[C.INTAKE_QUEUE].find_one_and_update(
            {"status": "pending"},
            {
                "$set": {
                    "status": "processing",
                    "updatedAt": now,
                    "error": None,
                }
            },
            sort=[("createdAt", 1)],
            return_document=ReturnDocument.AFTER,
        )
        if not doc:
            break
        claimed.append(doc)
    return claimed


def mark_done(
    item_id: str,
    *,
    job_id: str | None,
    fetch_status: str | None = None,
) -> None:
    now = _now()
    fields: dict[str, Any] = {
        "status": "done",
        "jobId": job_id,
        "error": None,
        "updatedAt": now,
        "processedAt": now,
    }
    if fetch_status is not None:
        fields["fetchStatus"] = fetch_status
    get_db()[C.INTAKE_QUEUE].update_one({"_id": item_id}, {"$set": fields})


def mark_failed(
    item_id: str,
    *,
    error: str,
    fetch_status: str | None = None,
) -> None:
    now = _now()
    fields: dict[str, Any] = {
        "status": "failed",
        "error": (error or "unknown error")[:500],
        "updatedAt": now,
        "processedAt": now,
    }
    if fetch_status is not None:
        fields["fetchStatus"] = fetch_status
    get_db()[C.INTAKE_QUEUE].update_one({"_id": item_id}, {"$set": fields})


def mark_needs_paste(
    item_id: str,
    *,
    error: str | None = None,
    fetch_status: str | None = "blocked",
) -> None:
    now = _now()
    fields: dict[str, Any] = {
        "status": "needsPaste",
        "error": (error or "Could not read that page. Paste the job description.")[:500],
        "updatedAt": now,
        "processedAt": None,
    }
    if fetch_status is not None:
        fields["fetchStatus"] = fetch_status
    get_db()[C.INTAKE_QUEUE].update_one({"_id": item_id}, {"$set": fields})


def count_by_status(*statuses: str) -> int:
    if not statuses:
        return 0
    return get_db()[C.INTAKE_QUEUE].count_documents({"status": {"$in": list(statuses)}})
