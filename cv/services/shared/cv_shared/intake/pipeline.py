"""Hourly ingest pipeline: Gmail → normalize → upsert → analyze."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .. import collections as C
from ..db import get_db
from ..matching import analyze_job
from .gmail_client import (
    build_gmail_service,
    credentials_available,
    gmail_query,
    processed_label_enabled,
)
from .gmail_source import message_to_raw_jobs
from .normalize import normalize_raw_job
from .upsert import upsert_normalized_job

logger = logging.getLogger(__name__)


def _mark_gmail_processed(service, message_id: str) -> None:
    if not processed_label_enabled():
        return
    label_name = "AI Job Agent/Processed"
    try:
        labels = service.users().labels().list(userId="me").execute().get("labels", [])
        label_id = next((l["id"] for l in labels if l.get("name") == label_name), None)
        if not label_id:
            created = (
                service.users()
                .labels()
                .create(
                    userId="me",
                    body={
                        "name": label_name,
                        "labelListVisibility": "labelShow",
                        "messageListVisibility": "show",
                    },
                )
                .execute()
            )
            label_id = created["id"]
        service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": [label_id]},
        ).execute()
    except Exception:
        logger.exception("Failed to apply processed label to %s", message_id)


def fetch_gmail_raw_jobs(max_messages: int = 40) -> tuple[list[dict], list[str]]:
    """Fetch unread-to-ingest Gmail alerts. Returns (raw_jobs, message_ids_seen)."""
    if not credentials_available():
        logger.warning("Gmail credentials missing; skipping ingest")
        return [], []

    service = build_gmail_service()
    query = gmail_query()
    db = get_db()
    raw_jobs: list[dict] = []
    message_ids: list[str] = []

    response = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_messages)
        .execute()
    )
    for item in response.get("messages") or []:
        mid = item["id"]
        message_ids.append(mid)
        if db[C.GMAIL_MESSAGES].find_one({"_id": mid}):
            continue
        full = (
            service.users()
            .messages()
            .get(userId="me", id=mid, format="full")
            .execute()
        )
        try:
            raw_jobs.extend(message_to_raw_jobs(full))
        except Exception:
            logger.exception("Failed parsing Gmail message %s", mid)

    return raw_jobs, message_ids


def run_ingest(
    *,
    analyze: bool = True,
    max_messages: int = 40,
    reprocess: bool = False,
) -> dict[str, Any]:
    """Run one ingest cycle. Safe to call from worker or API.

    reprocess=True clears cv_gmailMessages so previously seen alerts are fetched again
    (useful after a bug fixed mid-flight).
    """
    started = datetime.now(timezone.utc).isoformat()
    db = get_db()
    summary: dict[str, Any] = {
        "startedAt": started,
        "messagesSeen": 0,
        "messagesNew": 0,
        "jobsCreated": 0,
        "jobsUpdated": 0,
        "analyzed": 0,
        "outOfArea": 0,
        "skippedNoCreds": False,
        "reprocessCleared": 0,
        "errors": [],
    }

    if reprocess:
        cleared = db[C.GMAIL_MESSAGES].delete_many({}).deleted_count
        summary["reprocessCleared"] = cleared
        logger.info("Cleared %s processed Gmail message markers for reprocess", cleared)

    if not credentials_available():
        summary["skippedNoCreds"] = True
        summary["finishedAt"] = datetime.now(timezone.utc).isoformat()
        db[C.SYSTEM_RUNS].insert_one(
            {
                "type": "ingest",
                "startedAt": started,
                "finishedAt": summary["finishedAt"],
                "summary": summary,
            }
        )
        return summary

    try:
        raw_jobs, message_ids = fetch_gmail_raw_jobs(max_messages=max_messages)
    except Exception as exc:
        logger.exception("Gmail fetch failed")
        summary["errors"].append(str(exc))
        summary["finishedAt"] = datetime.now(timezone.utc).isoformat()
        db[C.SYSTEM_RUNS].insert_one(
            {
                "type": "ingest",
                "startedAt": started,
                "finishedAt": summary["finishedAt"],
                "summary": summary,
            }
        )
        return summary

    summary["messagesSeen"] = len(message_ids)
    service = None
    if processed_label_enabled():
        try:
            service = build_gmail_service()
        except Exception:
            service = None

    # Track which message ids produced jobs this run
    touched_messages: set[str] = set()
    succeeded_messages: set[str] = set()
    failed_messages: set[str] = set()
    for raw in raw_jobs:
        mid = (raw.get("discoveredBy") or {}).get("messageId")
        if mid:
            touched_messages.add(mid)
        try:
            normalized = normalize_raw_job(raw)
            result = upsert_normalized_job(normalized)
            job = result["job"]
            if mid:
                succeeded_messages.add(mid)
            if result["created"]:
                summary["jobsCreated"] += 1
            else:
                summary["jobsUpdated"] += 1
            if job.get("status") == "out_of_area":
                summary["outOfArea"] += 1
            elif (
                analyze
                and result["created"]
                and job.get("locationAssessment", {}).get("bayAreaEligible")
            ):
                try:
                    analyze_job(job["_id"])
                    summary["analyzed"] += 1
                except Exception as exc:
                    logger.exception("analyze failed for %s", job["_id"])
                    summary["errors"].append(f"analyze {job['_id']}: {exc}")
        except Exception as exc:
            logger.exception("upsert failed")
            summary["errors"].append(str(exc))
            if mid:
                failed_messages.add(mid)

    # Mark processed only when safe to skip forever:
    # - message had no extractable jobs, or
    # - at least one job upsert succeeded
    # Do NOT mark if every upsert for that message failed (allows retry after fixes).
    for mid in message_ids:
        if db[C.GMAIL_MESSAGES].find_one({"_id": mid}):
            continue
        if mid in failed_messages and mid not in succeeded_messages:
            logger.warning(
                "Leaving Gmail message %s unmarked — all job upserts failed", mid
            )
            continue
        if mid in touched_messages and mid not in succeeded_messages:
            # touched but somehow neither success nor fail tracked — leave unmarked
            continue
        db[C.GMAIL_MESSAGES].insert_one(
            {
                "_id": mid,
                "processedAt": datetime.now(timezone.utc).isoformat(),
                "hadJobs": mid in touched_messages,
            }
        )
        summary["messagesNew"] += 1
        if service:
            _mark_gmail_processed(service, mid)

    summary["finishedAt"] = datetime.now(timezone.utc).isoformat()
    db[C.SYSTEM_RUNS].insert_one(
        {
            "type": "ingest",
            "startedAt": started,
            "finishedAt": summary["finishedAt"],
            "summary": summary,
        }
    )
    logger.info("Ingest complete: %s", summary)
    return summary
