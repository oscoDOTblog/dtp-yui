"""Hourly / manual ingest: Gmail digests + Greenhouse boards + URL queue → analyze."""

from __future__ import annotations

import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from .. import collections as C
from ..db import get_db
from ..matching import analyze_job, seed_placeholders_from_description
from ..settings import (
    get_app_settings,
    ingest_drop_reason,
    is_ats_source_enabled,
    is_gmail_source_enabled,
)
from ..telegram import notify_apply_match
from .fetch_listing import enrich_raw_job
from .gmail_client import (
    build_gmail_service,
    credentials_available,
    gmail_query,
    processed_label_enabled,
)
from .gmail_source import message_to_raw_jobs
from .ashby_source import fetch_ashby_raw_jobs
from .greenhouse_source import fetch_greenhouse_raw_jobs
from .location import assess_location
from .manual_queue import (
    claim_pending,
    count_by_status,
    mark_done,
    mark_failed,
    mark_needs_paste,
)
from .normalize import normalize_raw_job
from .role_filter import assess_role_fit
from .upsert import upsert_normalized_job
from .url_to_raw import is_enrich_blocked_or_empty, queue_item_to_raw

logger = logging.getLogger(__name__)

_ingest_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ingest_max_listings() -> int:
    try:
        return max(1, int(os.environ.get("INGEST_MAX_LISTINGS", "500")))
    except ValueError:
        return 500


def _is_cancel_requested(run_id: str | None) -> bool:
    if not run_id:
        return False
    doc = get_db()[C.SYSTEM_RUNS].find_one(
        {"_id": run_id},
        {"cancelRequested": 1},
    )
    return bool(doc and doc.get("cancelRequested"))


def cancel_ingest(
    *,
    run_id: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Request cancel on the active ingest, or force-clear a stuck running lock."""
    db = get_db()
    if run_id:
        doc = db[C.SYSTEM_RUNS].find_one({"_id": run_id, "type": "ingest"})
    else:
        doc = get_running_ingest()

    if not doc:
        return {
            "ok": False,
            "found": False,
            "message": "No running ingest",
            "runId": run_id,
            "status": "idle",
        }

    rid = doc["_id"]
    if doc.get("status") != "running" and not force:
        return {
            "ok": True,
            "found": True,
            "runId": rid,
            "status": doc.get("status"),
            "message": f"Ingest already {doc.get('status')}",
            "forced": False,
        }

    if force:
        _patch_run(
            rid,
            {
                "cancelRequested": True,
                "status": "cancelled",
                "finishedAt": _now(),
                "currentTitle": "Cancelled (force clear)",
            },
        )
        return {
            "ok": True,
            "found": True,
            "runId": rid,
            "status": "cancelled",
            "forced": True,
            "message": "Ingest lock cleared",
        }

    _patch_run(
        rid,
        {
            "cancelRequested": True,
            "currentTitle": "Cancelling…",
        },
    )
    return {
        "ok": True,
        "found": True,
        "runId": rid,
        "status": "cancelling",
        "forced": False,
        "message": "Cancel requested",
    }


def _truncate_listings(
    raw_jobs: list[dict],
    *,
    remaining: int,
    label: str,
    max_listings: int,
    summary: dict[str, Any],
) -> tuple[list[dict], int]:
    """Truncate a batch to remaining budget. Returns (jobs, new_remaining)."""
    if remaining <= 0:
        if raw_jobs:
            msg = (
                f"Skipped {len(raw_jobs)} {label} listings "
                f"(INGEST_MAX_LISTINGS={max_listings} exhausted)"
            )
            summary.setdefault("errors", []).append(msg)
            summary["listingsTruncated"] = (
                summary.get("listingsTruncated", 0) + len(raw_jobs)
            )
        return [], 0
    if len(raw_jobs) <= remaining:
        return raw_jobs, remaining - len(raw_jobs)
    truncated = len(raw_jobs) - remaining
    msg = (
        f"Truncated {label} listings from {len(raw_jobs)} to {remaining} "
        f"(INGEST_MAX_LISTINGS={max_listings})"
    )
    summary.setdefault("errors", []).append(msg)
    summary["listingsTruncated"] = summary.get("listingsTruncated", 0) + truncated
    logger.warning(msg)
    return raw_jobs[:remaining], 0


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
    run_id: str | None = None,
) -> dict[str, set[str]]:
    """Normalize → upsert → analyze a list of raw jobs. Mutates summary."""
    touched_messages: set[str] = set()
    succeeded_messages: set[str] = set()
    failed_messages: set[str] = set()
    skipped_only_messages: set[str] = set()

    created_key = f"{count_prefix}JobsCreated" if count_prefix else None
    updated_key = f"{count_prefix}JobsUpdated" if count_prefix else None

    for raw in raw_jobs:
        if run_id and _is_cancel_requested(run_id):
            summary["status"] = "cancelled"
            summary["currentTitle"] = "Cancelled"
            summary["finishedAt"] = _now()
            publish()
            break

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
            # ATS boards / pre-fetched content — skip URL enrich.
            src = (raw.get("source") or "").strip().lower()
            if src in ("greenhouse", "ashby") or (
                raw.get("_queueMeta") or {}
            ).get("skipEnrich"):
                enriched = {k: v for k, v in raw.items() if k != "_queueMeta"}
            else:
                enriched = enrich_raw_job(
                    {k: v for k, v in raw.items() if k != "_queueMeta"}
                )
            enriched = seed_placeholders_from_description(enriched)
            normalized = normalize_raw_job(enriched)
            if enriched.get("fetchStatus"):
                normalized["fetchStatus"] = enriched["fetchStatus"]

            drop = ingest_drop_reason(normalized, app_settings)
            if drop:
                if drop == "outOfArea":
                    summary["outOfArea"] = summary.get("outOfArea", 0) + 1
                    summary["skippedOutOfArea"] = (
                        summary.get("skippedOutOfArea", 0) + 1
                    )
                else:
                    summary["wrongRole"] = summary.get("wrongRole", 0) + 1
                    summary["skippedWrongRole"] = (
                        summary.get("skippedWrongRole", 0) + 1
                    )
                if mid:
                    succeeded_messages.add(mid)
                    skipped_only_messages.discard(mid)
                summary["listingsProcessed"] = summary.get("listingsProcessed", 0) + 1
                publish()
                continue

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

            _analyze_after_upsert(
                job, created=result["created"], analyze=analyze, summary=summary
            )
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


def _refresh_job_assessments(job_id: str) -> dict[str, Any] | None:
    """Recompute location/role assessments after extract fills title/location/workMode.

    Does not change ``status`` — matches job-page Re-analyze, which leaves
    status as ``analyzed`` while assessments drive inbox chips/filters.
    """
    db = get_db()
    job = db[C.JOBS].find_one({"_id": job_id})
    if not job:
        return None
    description = job.get("descriptionRaw") or ""
    location_assessment = assess_location(
        location=job.get("location") or "",
        title=job.get("title") or "",
        description=description,
        work_mode_hint=job.get("workMode"),
    )
    role_assessment = assess_role_fit(
        title=job.get("title") or "",
        description=description,
    )
    updates: dict[str, Any] = {
        "locationAssessment": location_assessment,
        "roleAssessment": role_assessment,
    }
    arrangement = location_assessment.get("workArrangement")
    if arrangement and arrangement != "unknown":
        updates["workMode"] = arrangement
    db[C.JOBS].update_one({"_id": job_id}, {"$set": updates})
    return db[C.JOBS].find_one({"_id": job_id})


def _analyze_after_upsert(
    job: dict[str, Any],
    *,
    created: bool,
    analyze: bool,
    summary: dict[str, Any],
    force: bool = False,
) -> None:
    """Shared auto-analyze gate used by Gmail/Greenhouse/manual queue paths.

    ``force=True`` (manual URL queue): always run the same ``analyze_job`` path as
    the job-page Re-analyze button. Early Bay Area / role gates often fire while
    title/location are still placeholders, and existing matches skip re-analyze.
    """
    if not force:
        if job.get("status") == "out_of_area":
            summary["outOfArea"] = summary.get("outOfArea", 0) + 1
            return
        if job.get("status") == "wrong_role":
            summary["wrongRole"] = summary.get("wrongRole", 0) + 1
            return
    if not analyze:
        return
    db = get_db()

    if force:
        try:
            match = analyze_job(job["_id"])
            summary["analyzed"] = summary.get("analyzed", 0) + 1
            refreshed = _refresh_job_assessments(job["_id"]) or job
            loc_ok = bool(
                refreshed.get("locationAssessment", {}).get("bayAreaEligible")
            )
            role_ok = bool(refreshed.get("roleAssessment", {}).get("roleEligible"))
            if not loc_ok:
                summary["outOfArea"] = summary.get("outOfArea", 0) + 1
            elif not role_ok:
                summary["wrongRole"] = summary.get("wrongRole", 0) + 1
            elif notify_apply_match(refreshed, match):
                summary["telegramSent"] = summary.get("telegramSent", 0) + 1
        except Exception as exc:
            logger.exception("analyze failed for %s", job["_id"])
            summary["errors"].append(f"analyze {job['_id']}: {exc}")
        return

    eligible = bool(
        job.get("locationAssessment", {}).get("bayAreaEligible")
        and job.get("roleAssessment", {}).get("roleEligible")
    )
    # Legacy jobs without roleAssessment: treat missing as eligible only if status is new
    if job.get("roleAssessment") is None and job.get("status") not in (
        "out_of_area",
        "wrong_role",
    ):
        eligible = bool(job.get("locationAssessment", {}).get("bayAreaEligible"))

    if created and eligible:
        try:
            match = analyze_job(job["_id"])
            summary["analyzed"] += 1
            if notify_apply_match(job, match):
                summary["telegramSent"] += 1
        except Exception as exc:
            logger.exception("analyze failed for %s", job["_id"])
            summary["errors"].append(f"analyze {job['_id']}: {exc}")
        return
    if not created and eligible and job.get("status") not in (
        "out_of_area",
        "wrong_role",
    ):
        existing_match = db[C.JOB_MATCHES].find_one({"jobId": job["_id"]})
        if not existing_match:
            try:
                match = analyze_job(job["_id"])
                summary["analyzed"] += 1
                if notify_apply_match(job, match):
                    summary["telegramSent"] += 1
            except Exception as exc:
                summary["errors"].append(f"analyze {job['_id']}: {exc}")


def _drain_manual_queue(
    summary: dict[str, Any],
    *,
    analyze: bool,
    publish: Callable[..., None],
    limit: int = 40,
    run_id: str | None = None,
) -> None:
    """Claim pending URL queue items and ingest them through normalize/upsert."""
    claim_limit = max(0, min(limit, ingest_max_listings()))
    if claim_limit <= 0:
        return
    claimed = claim_pending(limit=claim_limit)
    summary["listingsTotal"] = summary.get("listingsTotal", 0) + len(claimed)
    summary["queueClaimed"] = len(claimed)
    publish()

    for item in claimed:
        if run_id and _is_cancel_requested(run_id):
            summary["status"] = "cancelled"
            summary["currentTitle"] = "Cancelled"
            summary["finishedAt"] = _now()
            publish()
            break

        queue_id = item["_id"]
        title_label = item.get("url") or queue_id
        summary["currentTitle"] = f"Queue: {title_label}"
        publish()
        try:
            raw = queue_item_to_raw(item)
            queue_meta = raw.pop("_queueMeta", {}) or {}
            raw_title = (raw.get("title") or "").strip()
            raw_company = (raw.get("company") or "").strip()
            if raw_title and raw_title not in ("Untitled", "Untitled role"):
                title_label = f"{raw_title} @ {raw_company or '?'}"
                summary["currentTitle"] = f"Queue: {title_label}"
                publish()
            src = (raw.get("source") or "").strip().lower()
            if queue_meta.get("skipEnrich") or src in ("greenhouse", "ashby"):
                enriched = raw
            else:
                enriched = enrich_raw_job(raw)

            if queue_meta.get("needsPasteIfBlocked") and is_enrich_blocked_or_empty(
                enriched
            ):
                mark_needs_paste(
                    queue_id,
                    error="Could not read that page. Paste the job description.",
                    fetch_status=enriched.get("fetchStatus") or "blocked",
                )
                summary["queueNeedsPaste"] = summary.get("queueNeedsPaste", 0) + 1
                summary["listingsProcessed"] = summary.get("listingsProcessed", 0) + 1
                publish()
                continue

            # Fill placeholders from description before Bay Area / role gates
            enriched = seed_placeholders_from_description(enriched)

            normalized = normalize_raw_job(enriched)
            if enriched.get("fetchStatus"):
                normalized["fetchStatus"] = enriched["fetchStatus"]

            drop = ingest_drop_reason(normalized, get_app_settings())
            if drop:
                if drop == "outOfArea":
                    summary["outOfArea"] = summary.get("outOfArea", 0) + 1
                    summary["skippedOutOfArea"] = (
                        summary.get("skippedOutOfArea", 0) + 1
                    )
                    drop_msg = "Dropped before analyze: out of area"
                else:
                    summary["wrongRole"] = summary.get("wrongRole", 0) + 1
                    summary["skippedWrongRole"] = (
                        summary.get("skippedWrongRole", 0) + 1
                    )
                    drop_msg = "Dropped before analyze: wrong role"
                mark_failed(
                    queue_id,
                    error=drop_msg,
                    fetch_status=enriched.get("fetchStatus"),
                )
                summary["listingsProcessed"] = summary.get("listingsProcessed", 0) + 1
                publish()
                continue

            result = upsert_normalized_job(normalized)
            job = result["job"]
            if result["created"]:
                summary["jobsCreated"] += 1
                summary["manualJobsCreated"] = summary.get("manualJobsCreated", 0) + 1
            else:
                summary["jobsUpdated"] += 1
                summary["manualJobsUpdated"] = summary.get("manualJobsUpdated", 0) + 1

            progress_title = (job.get("title") or "").strip()
            progress_company = (job.get("company") or "").strip()
            if progress_title and progress_title not in ("Untitled", "Untitled role"):
                summary["currentTitle"] = (
                    f"Analyzing: {progress_title} @ {progress_company or '?'}"
                )
                publish()

            # Same path as job-page Re-analyze — do not skip on early gates / existing match
            _analyze_after_upsert(
                job,
                created=result["created"],
                analyze=analyze,
                summary=summary,
                force=True,
            )
            job = get_db()[C.JOBS].find_one({"_id": job["_id"]}) or job
            mark_done(
                queue_id,
                job_id=job.get("_id"),
                fetch_status=enriched.get("fetchStatus"),
                job_title=job.get("title"),
                job_company=job.get("company"),
            )
        except Exception as exc:
            logger.exception("manual queue ingest failed for %s", queue_id)
            summary["errors"].append(f"queue {queue_id}: {exc}")
            mark_failed(queue_id, error=str(exc))

        summary["listingsProcessed"] = summary.get("listingsProcessed", 0) + 1
        publish()

    summary["queuePending"] = count_by_status("pending")


def run_ingest(
    *,
    analyze: bool = True,
    max_messages: int = 40,
    reprocess: bool = False,
    run_id: str | None = None,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
    sources: str = "all",
    greenhouse_source_ids: list[str] | None = None,
    ashby_source_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Run one ingest cycle. sources: all | gmail | greenhouse | ashby | manual."""
    started = _now()
    db = get_db()
    run_id = run_id or f"ingest_{uuid.uuid4().hex[:16]}"
    sources_mode = (sources or "all").strip().lower()
    if sources_mode not in ("all", "gmail", "greenhouse", "ashby", "manual"):
        sources_mode = "all"

    summary: dict[str, Any] = {
        "startedAt": started,
        "messagesSeen": 0,
        "messagesNew": 0,
        "jobsCreated": 0,
        "jobsUpdated": 0,
        "analyzed": 0,
        "outOfArea": 0,
        "wrongRole": 0,
        "skippedOutOfArea": 0,
        "skippedWrongRole": 0,
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
        "ashbyJobsCreated": 0,
        "ashbyJobsUpdated": 0,
        "manualJobsCreated": 0,
        "manualJobsUpdated": 0,
        "queueClaimed": 0,
        "queuePending": 0,
        "queueNeedsPaste": 0,
        "sourcesPolled": 0,
        "sourcesFailed": 0,
        "listingsTruncated": 0,
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
            "wrongRole": summary.get("wrongRole", 0),
            "currentTitle": summary.get("currentTitle", ""),
            "errors": summary.get("errors", []),
            "cancelRequested": bool(
                summary.get("status") == "cancelled"
                or _is_cancel_requested(run_id)
            ),
            "startedAt": started,
        }
        if summary.get("finishedAt"):
            payload["finishedAt"] = summary["finishedAt"]
        _patch_run(run_id, payload)
        if progress_cb:
            progress_cb(payload)

    def was_cancelled() -> bool:
        if summary.get("status") == "cancelled":
            return True
        if _is_cancel_requested(run_id):
            summary["status"] = "cancelled"
            summary["currentTitle"] = "Cancelled"
            summary["finishedAt"] = _now()
            publish()
            return True
        return False

    if reprocess and sources_mode in ("all", "gmail"):
        cleared = db[C.GMAIL_MESSAGES].delete_many({}).deleted_count
        summary["reprocessCleared"] = cleared
        logger.info("Cleared %s processed Gmail message markers for reprocess", cleared)
        publish()

    app_settings = get_app_settings()
    run_gmail = sources_mode in ("all", "gmail")
    run_greenhouse = sources_mode in ("all", "greenhouse")
    run_ashby = sources_mode in ("all", "ashby")
    run_manual = sources_mode in ("all", "manual")
    max_listings = ingest_max_listings()
    remaining = max_listings

    # --- Gmail ---
    message_ids: list[str] = []
    gmail_sets: dict[str, set[str]] = {
        "touched": set(),
        "succeeded": set(),
        "failed": set(),
        "skipped_only": set(),
    }

    if run_gmail and not was_cancelled():
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
            raw_jobs, remaining = _truncate_listings(
                raw_jobs,
                remaining=remaining,
                label="Gmail",
                max_listings=max_listings,
                summary=summary,
            )
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
                run_id=run_id,
            )

            if not was_cancelled():
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
                        # Partial cancel mid-message: leave unmarked so reprocess can finish
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
    if run_greenhouse and not was_cancelled():
        if not is_ats_source_enabled("greenhouse", app_settings):
            summary["skippedDisabledAts"] = {
                **(summary.get("skippedDisabledAts") or {}),
                "greenhouse": True,
            }
            publish()
        else:
            try:
                gh_raw, gh_stats = fetch_greenhouse_raw_jobs(
                    source_ids=greenhouse_source_ids,
                    app_settings=app_settings,
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
            summary["greenhouseJobsListed"] = gh_stats.get("jobsListed", 0)
            summary["greenhouseJobsPrefiltered"] = gh_stats.get(
                "jobsPrefiltered", 0
            )
            summary["greenhouseTwoPhase"] = bool(gh_stats.get("twoPhase"))
            summary["skippedOutOfArea"] = summary.get("skippedOutOfArea", 0) + int(
                gh_stats.get("skippedOutOfArea") or 0
            )
            summary["skippedWrongRole"] = summary.get("skippedWrongRole", 0) + int(
                gh_stats.get("skippedWrongRole") or 0
            )
            summary["skippedSourceLocation"] = int(
                gh_stats.get("skippedSourceLocation") or 0
            )
            gh_raw, remaining = _truncate_listings(
                gh_raw,
                remaining=remaining,
                label="Greenhouse",
                max_listings=max_listings,
                summary=summary,
            )
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
                run_id=run_id,
            )

    # --- Ashby ---
    if run_ashby and not was_cancelled():
        if not is_ats_source_enabled("ashby", app_settings):
            summary["skippedDisabledAts"] = {
                **(summary.get("skippedDisabledAts") or {}),
                "ashby": True,
            }
            publish()
        else:
            try:
                ashby_raw, ashby_stats = fetch_ashby_raw_jobs(
                    source_ids=ashby_source_ids,
                    app_settings=app_settings,
                )
            except Exception as exc:
                logger.exception("Ashby fetch failed")
                summary["errors"].append(f"ashby: {exc}")
                ashby_raw, ashby_stats = [], {
                    "sourcesPolled": 0,
                    "sourcesFailed": 0,
                    "jobsFetched": 0,
                }

            summary["sourcesPolled"] = summary.get("sourcesPolled", 0) + int(
                ashby_stats.get("sourcesPolled") or 0
            )
            summary["sourcesFailed"] = summary.get("sourcesFailed", 0) + int(
                ashby_stats.get("sourcesFailed") or 0
            )
            summary["ashbyJobsListed"] = ashby_stats.get("jobsListed", 0)
            summary["ashbyJobsPrefiltered"] = ashby_stats.get("jobsPrefiltered", 0)
            summary["skippedOutOfArea"] = summary.get("skippedOutOfArea", 0) + int(
                ashby_stats.get("skippedOutOfArea") or 0
            )
            summary["skippedWrongRole"] = summary.get("skippedWrongRole", 0) + int(
                ashby_stats.get("skippedWrongRole") or 0
            )
            summary["skippedSourceLocation"] = summary.get(
                "skippedSourceLocation", 0
            ) + int(ashby_stats.get("skippedSourceLocation") or 0)
            ashby_raw, remaining = _truncate_listings(
                ashby_raw,
                remaining=remaining,
                label="Ashby",
                max_listings=max_listings,
                summary=summary,
            )
            summary["listingsTotal"] = summary.get("listingsTotal", 0) + len(ashby_raw)
            publish()

            _ingest_raw_jobs(
                ashby_raw,
                summary,
                analyze=analyze,
                app_settings=app_settings,
                publish=publish,
                gate_gmail=False,
                count_prefix="ashby",
                run_id=run_id,
            )

    # --- Manual URL queue ---
    if run_manual and not was_cancelled():
        try:
            _drain_manual_queue(
                summary,
                analyze=analyze,
                publish=publish,
                limit=min(40, remaining if remaining > 0 else 0),
                run_id=run_id,
            )
        except Exception as exc:
            logger.exception("Manual queue drain failed")
            summary["errors"].append(f"manual-queue: {exc}")

    if was_cancelled() or summary.get("status") == "cancelled":
        summary["status"] = "cancelled"
        summary["currentTitle"] = ""
        if not summary.get("finishedAt"):
            summary["finishedAt"] = _now()
        publish()
        logger.info("Ingest cancelled: %s", summary)
        return {"runId": run_id, **summary}

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
    sources: str = "all",
    greenhouse_source_ids: list[str] | None = None,
    ashby_source_ids: list[str] | None = None,
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
                "cancelRequested": False,
                "listingsTotal": 0,
                "listingsProcessed": 0,
                "jobsCreated": 0,
                "analyzed": 0,
                "outOfArea": 0,
                "wrongRole": 0,
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
                    ashby_source_ids=ashby_source_ids,
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
