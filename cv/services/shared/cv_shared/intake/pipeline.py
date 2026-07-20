"""Hourly / manual ingest: Gmail digests → per-listing jobs → analyze."""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from .. import collections as C
from ..db import get_db
from ..matching import analyze_job
from ..telegram import notify_apply_match
from .fetch_listing import enrich_raw_job
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

_ingest_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def get_running_ingest() -> dict | None:
    db = get_db()
    return db[C.SYSTEM_RUNS].find_one(
        {"type": "ingest", "status": "running"},
        sort=[("startedAt", -1)],
    )


def get_ingest_status(run_id: str | None = None) -> dict | None:
    db = get_db()
    if run_id:
        return db[C.SYSTEM_RUNS].find_one({"_id": run_id})
    running = get_running_ingest()
    if running:
        return running
    return db[C.SYSTEM_RUNS].find_one(
        {"type": "ingest"},
        sort=[("startedAt", -1)],
    )


def _patch_run(run_id: str, fields: dict[str, Any]) -> None:
    get_db()[C.SYSTEM_RUNS].update_one({"_id": run_id}, {"$set": fields})


def run_ingest(
    *,
    analyze: bool = True,
    max_messages: int = 40,
    reprocess: bool = False,
    run_id: str | None = None,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run one ingest cycle sequentially. Updates run_id progress when provided."""
    started = _now()
    db = get_db()
    run_id = run_id or f"ingest_{uuid.uuid4().hex[:16]}"

    summary: dict[str, Any] = {
        "startedAt": started,
        "messagesSeen": 0,
        "messagesNew": 0,
        "jobsCreated": 0,
        "jobsUpdated": 0,
        "analyzed": 0,
        "outOfArea": 0,
        "listingsTotal": 0,
        "listingsProcessed": 0,
        "telegramSent": 0,
        "skippedNoCreds": False,
        "reprocessCleared": 0,
        "currentTitle": "",
        "errors": [],
        "status": "running",
    }

    existing = db[C.SYSTEM_RUNS].find_one({"_id": run_id})
    if not existing:
        db[C.SYSTEM_RUNS].insert_one(
            {
                "_id": run_id,
                "type": "ingest",
                "status": "running",
                "startedAt": started,
                **{k: summary[k] for k in summary if k != "status"},
            }
        )

    def publish(**extra: Any) -> None:
        summary.update(extra)
        payload = {
            "status": summary.get("status", "running"),
            "summary": {k: v for k, v in summary.items() if k != "status"},
            "listingsTotal": summary.get("listingsTotal", 0),
            "listingsProcessed": summary.get("listingsProcessed", 0),
            "jobsCreated": summary.get("jobsCreated", 0),
            "analyzed": summary.get("analyzed", 0),
            "outOfArea": summary.get("outOfArea", 0),
            "currentTitle": summary.get("currentTitle", ""),
            "errors": summary.get("errors", []),
            "startedAt": started,
        }
        if summary.get("finishedAt"):
            payload["finishedAt"] = summary["finishedAt"]
        _patch_run(run_id, payload)
        if progress_cb:
            progress_cb(payload)

    if reprocess:
        cleared = db[C.GMAIL_MESSAGES].delete_many({}).deleted_count
        summary["reprocessCleared"] = cleared
        logger.info("Cleared %s processed Gmail message markers for reprocess", cleared)
        publish()

    if not credentials_available():
        summary["skippedNoCreds"] = True
        summary["status"] = "completed"
        summary["finishedAt"] = _now()
        publish()
        return {"runId": run_id, **summary}

    try:
        raw_jobs, message_ids = fetch_gmail_raw_jobs(max_messages=max_messages)
    except Exception as exc:
        logger.exception("Gmail fetch failed")
        summary["errors"].append(str(exc))
        summary["status"] = "failed"
        summary["finishedAt"] = _now()
        publish()
        return {"runId": run_id, **summary}

    summary["messagesSeen"] = len(message_ids)
    summary["listingsTotal"] = len(raw_jobs)
    publish()

    service = None
    if processed_label_enabled():
        try:
            service = build_gmail_service()
        except Exception:
            service = None

    touched_messages: set[str] = set()
    succeeded_messages: set[str] = set()
    failed_messages: set[str] = set()

    for raw in raw_jobs:
        mid = (raw.get("discoveredBy") or {}).get("messageId")
        if mid:
            touched_messages.add(mid)
        title_label = f"{raw.get('title') or 'Untitled'} @ {raw.get('company') or '?'}"
        summary["currentTitle"] = title_label
        publish()

        try:
            enriched = enrich_raw_job(raw)
            normalized = normalize_raw_job(enriched)
            if enriched.get("fetchStatus"):
                normalized["fetchStatus"] = enriched["fetchStatus"]
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
                    match = analyze_job(job["_id"])
                    summary["analyzed"] += 1
                    if notify_apply_match(job, match):
                        summary["telegramSent"] += 1
                except Exception as exc:
                    logger.exception("analyze failed for %s", job["_id"])
                    summary["errors"].append(f"analyze {job['_id']}: {exc}")
            elif analyze and not result["created"]:
                # Re-analyze only if never analyzed and eligible
                existing_match = db[C.JOB_MATCHES].find_one({"jobId": job["_id"]})
                if (
                    not existing_match
                    and job.get("locationAssessment", {}).get("bayAreaEligible")
                    and job.get("status") not in ("out_of_area",)
                ):
                    try:
                        match = analyze_job(job["_id"])
                        summary["analyzed"] += 1
                        if notify_apply_match(job, match):
                            summary["telegramSent"] += 1
                    except Exception as exc:
                        summary["errors"].append(f"analyze {job['_id']}: {exc}")
        except Exception as exc:
            logger.exception("listing ingest failed")
            summary["errors"].append(str(exc))
            if mid:
                failed_messages.add(mid)

        summary["listingsProcessed"] = summary.get("listingsProcessed", 0) + 1
        publish()

    for mid in message_ids:
        if db[C.GMAIL_MESSAGES].find_one({"_id": mid}):
            continue
        if mid in failed_messages and mid not in succeeded_messages:
            logger.warning(
                "Leaving Gmail message %s unmarked — all job upserts failed", mid
            )
            continue
        if mid in touched_messages and mid not in succeeded_messages:
            continue
        db[C.GMAIL_MESSAGES].insert_one(
            {
                "_id": mid,
                "processedAt": _now(),
                "hadJobs": mid in touched_messages,
            }
        )
        summary["messagesNew"] += 1
        if service:
            _mark_gmail_processed(service, mid)

    summary["currentTitle"] = ""
    summary["status"] = "completed"
    summary["finishedAt"] = _now()
    publish()
    logger.info("Ingest complete: %s", summary)
    return {"runId": run_id, **summary}


def start_ingest_async(
    *,
    analyze: bool = True,
    reprocess: bool = False,
) -> dict[str, Any]:
    """Single-flight background ingest for the API. Returns immediately."""
    with _ingest_lock:
        running = get_running_ingest()
        if running:
            return {
                "accepted": False,
                "conflict": True,
                "runId": running.get("_id"),
                "status": "running",
                "message": "Ingest already running",
            }

        run_id = f"ingest_{uuid.uuid4().hex[:16]}"
        get_db()[C.SYSTEM_RUNS].insert_one(
            {
                "_id": run_id,
                "type": "ingest",
                "status": "running",
                "startedAt": _now(),
                "listingsTotal": 0,
                "listingsProcessed": 0,
                "jobsCreated": 0,
                "analyzed": 0,
                "outOfArea": 0,
                "currentTitle": "Starting…",
                "errors": [],
                "summary": {},
            }
        )

        def _worker() -> None:
            try:
                run_ingest(analyze=analyze, reprocess=reprocess, run_id=run_id)
            except Exception:
                logger.exception("background ingest failed")
                _patch_run(
                    run_id,
                    {
                        "status": "failed",
                        "finishedAt": _now(),
                        "errors": ["background ingest crashed"],
                    },
                )

        thread = threading.Thread(target=_worker, name=f"ingest-{run_id}", daemon=True)
        thread.start()
        return {
            "accepted": True,
            "conflict": False,
            "runId": run_id,
            "status": "running",
        }
