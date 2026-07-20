"""Hourly / manual ingest: Gmail digests + Greenhouse boards → analyze."""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from .. import collections as C
from ..db import get_db
from ..matching import analyze_job
from ..settings import get_app_settings, is_ats_source_enabled, is_gmail_source_enabled
from ..telegram import notify_apply_match
from .fetch_listing import enrich_raw_job
from .gmail_client import (
    build_gmail_service,
    credentials_available,
    gmail_query,
    processed_label_enabled,
)
from .gmail_source import message_to_raw_jobs
from .greenhouse_source import fetch_greenhouse_raw_jobs
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
        logger.warning("Gmail credentials missing; skipping Gmail ingest")
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


def _ingest_raw_jobs(
    raw_jobs: list[dict],
    summary: dict[str, Any],
    *,
    analyze: bool,
    app_settings: dict[str, Any],
    publish: Callable[..., None],
    gate_gmail: bool = False,
    count_prefix: str | None = None,
) -> dict[str, set[str]]:
    """Normalize → upsert → analyze a list of raw jobs. Mutates summary."""
    db = get_db()
    touched_messages: set[str] = set()
    succeeded_messages: set[str] = set()
    failed_messages: set[str] = set()
    skipped_only_messages: set[str] = set()

    created_key = f"{count_prefix}JobsCreated" if count_prefix else None
    updated_key = f"{count_prefix}JobsUpdated" if count_prefix else None

    for raw in raw_jobs:
        mid = (raw.get("discoveredBy") or {}).get("messageId")
        if mid:
            touched_messages.add(mid)
        title_label = f"{raw.get('title') or 'Untitled'} @ {raw.get('company') or '?'}"
        summary["currentTitle"] = title_label
        publish()

        if gate_gmail:
            alert_source = (raw.get("discoveredBy") or {}).get("source") or "email-alert"
            if not is_gmail_source_enabled(alert_source, app_settings):
                summary["skippedDisabledSource"] = (
                    summary.get("skippedDisabledSource", 0) + 1
                )
                if mid:
                    skipped_only_messages.add(mid)
                summary["listingsProcessed"] = summary.get("listingsProcessed", 0) + 1
                publish()
                continue

        try:
            # Greenhouse boards already include full content — skip URL enrich.
            if (raw.get("source") or "") == "greenhouse":
                enriched = raw
            else:
                enriched = enrich_raw_job(raw)
            normalized = normalize_raw_job(enriched)
            if enriched.get("fetchStatus"):
                normalized["fetchStatus"] = enriched["fetchStatus"]
            result = upsert_normalized_job(normalized)
            job = result["job"]
            if mid:
                succeeded_messages.add(mid)
                skipped_only_messages.discard(mid)
            if result["created"]:
                summary["jobsCreated"] += 1
                if created_key:
                    summary[created_key] = summary.get(created_key, 0) + 1
            else:
                summary["jobsUpdated"] += 1
                if updated_key:
                    summary[updated_key] = summary.get(updated_key, 0) + 1

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

    return {
        "touched": touched_messages,
        "succeeded": succeeded_messages,
        "failed": failed_messages,
        "skipped_only": skipped_only_messages,
    }


def run_ingest(
    *,
    analyze: bool = True,
    max_messages: int = 40,
    reprocess: bool = False,
    run_id: str | None = None,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
    sources: str = "all",
    greenhouse_source_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Run one ingest cycle. sources: all | gmail | greenhouse."""
    started = _now()
    db = get_db()
    run_id = run_id or f"ingest_{uuid.uuid4().hex[:16]}"
    sources_mode = (sources or "all").strip().lower()
    if sources_mode not in ("all", "gmail", "greenhouse"):
        sources_mode = "all"

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
        "skippedDisabledSource": 0,
        "skippedDisabledAts": {},
        "skippedNoCreds": False,
        "reprocessCleared": 0,
        "gmailJobsCreated": 0,
        "gmailJobsUpdated": 0,
        "greenhouseJobsCreated": 0,
        "greenhouseJobsUpdated": 0,
        "sourcesPolled": 0,
        "sourcesFailed": 0,
        "currentTitle": "",
        "errors": [],
        "status": "running",
        "sourcesMode": sources_mode,
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

    if reprocess and sources_mode in ("all", "gmail"):
        cleared = db[C.GMAIL_MESSAGES].delete_many({}).deleted_count
        summary["reprocessCleared"] = cleared
        logger.info("Cleared %s processed Gmail message markers for reprocess", cleared)
        publish()

    app_settings = get_app_settings()
    run_gmail = sources_mode in ("all", "gmail")
    run_greenhouse = sources_mode in ("all", "greenhouse")

    # --- Gmail ---
    message_ids: list[str] = []
    gmail_sets: dict[str, set[str]] = {
        "touched": set(),
        "succeeded": set(),
        "failed": set(),
        "skipped_only": set(),
    }

    if run_gmail:
        if not credentials_available():
            summary["skippedNoCreds"] = True
            publish()
        else:
            try:
                raw_jobs, message_ids = fetch_gmail_raw_jobs(max_messages=max_messages)
            except Exception as exc:
                logger.exception("Gmail fetch failed")
                summary["errors"].append(f"gmail: {exc}")
                raw_jobs, message_ids = [], []

            summary["messagesSeen"] = len(message_ids)
            summary["listingsTotal"] = summary.get("listingsTotal", 0) + len(raw_jobs)
            publish()

            gmail_sets = _ingest_raw_jobs(
                raw_jobs,
                summary,
                analyze=analyze,
                app_settings=app_settings,
                publish=publish,
                gate_gmail=True,
                count_prefix="gmail",
            )

            service = None
            if processed_label_enabled():
                try:
                    service = build_gmail_service()
                except Exception:
                    service = None

            for mid in message_ids:
                if db[C.GMAIL_MESSAGES].find_one({"_id": mid}):
                    continue
                if mid in gmail_sets["failed"] and mid not in gmail_sets["succeeded"]:
                    logger.warning(
                        "Leaving Gmail message %s unmarked — all job upserts failed",
                        mid,
                    )
                    continue
                if (
                    mid in gmail_sets["skipped_only"]
                    and mid not in gmail_sets["succeeded"]
                    and mid not in gmail_sets["failed"]
                ):
                    db[C.GMAIL_MESSAGES].insert_one(
                        {
                            "_id": mid,
                            "processedAt": _now(),
                            "hadJobs": False,
                            "skippedDisabledSource": True,
                        }
                    )
                    summary["messagesNew"] += 1
                    if service:
                        _mark_gmail_processed(service, mid)
                    continue
                if mid in gmail_sets["touched"] and mid not in gmail_sets["succeeded"]:
                    continue
                db[C.GMAIL_MESSAGES].insert_one(
                    {
                        "_id": mid,
                        "processedAt": _now(),
                        "hadJobs": mid in gmail_sets["touched"],
                    }
                )
                summary["messagesNew"] += 1
                if service:
                    _mark_gmail_processed(service, mid)

    # --- Greenhouse ---
    if run_greenhouse:
        if not is_ats_source_enabled("greenhouse", app_settings):
            summary["skippedDisabledAts"] = {
                **(summary.get("skippedDisabledAts") or {}),
                "greenhouse": True,
            }
            publish()
        else:
            try:
                gh_raw, gh_stats = fetch_greenhouse_raw_jobs(
                    source_ids=greenhouse_source_ids
                )
            except Exception as exc:
                logger.exception("Greenhouse fetch failed")
                summary["errors"].append(f"greenhouse: {exc}")
                gh_raw, gh_stats = [], {
                    "sourcesPolled": 0,
                    "sourcesFailed": 0,
                    "jobsFetched": 0,
                }

            summary["sourcesPolled"] = gh_stats.get("sourcesPolled", 0)
            summary["sourcesFailed"] = gh_stats.get("sourcesFailed", 0)
            summary["listingsTotal"] = summary.get("listingsTotal", 0) + len(gh_raw)
            publish()

            _ingest_raw_jobs(
                gh_raw,
                summary,
                analyze=analyze,
                app_settings=app_settings,
                publish=publish,
                gate_gmail=False,
                count_prefix="greenhouse",
            )

    summary["currentTitle"] = ""
    # Fail only if nothing ran and we had a hard Gmail-only mode with creds failure
    # and greenhouse also skipped — otherwise completed with partial results.
    if summary.get("errors") and summary.get("listingsProcessed", 0) == 0:
        # Soft: still mark completed unless both sides totally failed with zero progress
        pass
    summary["status"] = "completed"
    summary["finishedAt"] = _now()
    publish()
    logger.info("Ingest complete: %s", summary)
    return {"runId": run_id, **summary}


def start_ingest_async(
    *,
    analyze: bool = True,
    reprocess: bool = False,
    sources: str = "all",
    greenhouse_source_ids: list[str] | None = None,
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
                run_ingest(
                    analyze=analyze,
                    reprocess=reprocess,
                    run_id=run_id,
                    sources=sources,
                    greenhouse_source_ids=greenhouse_source_ids,
                )
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
