"""Stage 6 apply-agent helpers: Glassdoor ingest, runs, events, answer bank."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any

from . import collections as C
from .db import get_db
from .intake.html_markdown import description_fields_from_html_or_text
from .intake.normalize import normalize_raw_job
from .intake.upsert import upsert_normalized_job
from .matching import analyze_job

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def ingest_glassdoor_job(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize + upsert a Glassdoor-extracted listing; optionally analyze."""
    description = (payload.get("descriptionRaw") or "").strip()
    fields = description_fields_from_html_or_text(description)
    description = fields["descriptionRaw"] or description
    source_job_id = (payload.get("sourceJobId") or "").strip() or None
    source_url = (payload.get("sourceUrl") or "").strip() or None
    apply_url = (
        (payload.get("canonicalApplyUrl") or "").strip()
        or source_url
    )
    external_id = None
    if source_job_id:
        external_id = f"glassdoor:{source_job_id}"
    elif source_url:
        external_id = f"glassdoor:url:{hashlib.sha256(source_url.encode()).hexdigest()[:16]}"

    raw = {
        "source": "glassdoor",
        "externalId": external_id,
        "sourceUrl": source_url,
        "canonicalApplyUrl": apply_url,
        "title": payload.get("title"),
        "company": payload.get("company"),
        "location": payload.get("location"),
        "salary": payload.get("salary"),
        "descriptionText": description,
        "descriptionMarkdown": fields.get("descriptionMarkdown"),
        "discoveredBy": {
            "source": "glassdoor",
            "agent": True,
        },
    }
    normalized = normalize_raw_job(raw)
    result = upsert_normalized_job(normalized)
    job = result["job"]
    match = None
    if payload.get("analyze", True) and job.get("status") not in (
        "out_of_area",
        "wrong_role",
    ):
        try:
            match = analyze_job(job["_id"])
        except Exception:
            logger.exception("analyze after glassdoor ingest failed")
    return {
        "job": job,
        "created": result["created"],
        "reason": result.get("reason"),
        "match": match,
    }


def create_application_run(payload: dict[str, Any]) -> dict[str, Any]:
    db = get_db()
    run_id = _slug_id("run", _now(), payload.get("query") or "glassdoor")
    doc = {
        "_id": run_id,
        "source": payload.get("source") or "glassdoor",
        "query": payload.get("query"),
        "location": payload.get("location"),
        "searchUrl": payload.get("searchUrl"),
        "config": payload.get("config") or {},
        "state": payload.get("state") or "GLASSDOOR_SEARCHING",
        "uiMode": payload.get("uiMode"),
        "currentJob": payload.get("currentJob"),
        "resultsViewed": 0,
        "jobsExtracted": 0,
        "applicationsSubmitted": 0,
        "startedAt": _now(),
        "finishedAt": None,
        "error": None,
    }
    db[C.APPLICATION_RUNS].insert_one(doc)
    return doc


def patch_application_run(run_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    db = get_db()
    allowed = {
        "state",
        "uiMode",
        "currentJob",
        "resultsViewed",
        "jobsExtracted",
        "applicationsSubmitted",
        "finishedAt",
        "error",
        "config",
    }
    updates = {k: v for k, v in payload.items() if k in allowed}
    if not updates:
        return db[C.APPLICATION_RUNS].find_one({"_id": run_id})
    updates["updatedAt"] = _now()
    db[C.APPLICATION_RUNS].update_one({"_id": run_id}, {"$set": updates})
    return db[C.APPLICATION_RUNS].find_one({"_id": run_id})


def append_application_event(run_id: str, event: dict[str, Any]) -> dict[str, Any]:
    db = get_db()
    seq = event.get("sequence")
    if seq is None:
        last = db[C.APPLICATION_EVENTS].find_one(
            {"runId": run_id}, sort=[("sequence", -1)]
        )
        seq = int((last or {}).get("sequence") or 0) + 1
    event_id = f"evt_{run_id}_{seq}"
    # Do not persist raw sensitive field values from agent payloads.
    safe = {
        "_id": event_id,
        "runId": run_id,
        "sequence": seq,
        "type": event.get("type") or "UNKNOWN",
        "state": event.get("state"),
        "uiMode": event.get("uiMode"),
        "message": event.get("message"),
        "action": event.get("action"),
        "target": event.get("target"),
        "decision": event.get("decision"),
        "reason": event.get("reason"),
        "confidence": event.get("confidence"),
        "evidence": event.get("evidence"),
        "concerns": event.get("concerns"),
        "score": event.get("score"),
        "atsType": event.get("atsType"),
        "pageUrl": event.get("pageUrl"),
        "requestId": event.get("requestId"),
        "question": event.get("question"),
        "options": event.get("options"),
        "riskLevel": event.get("riskLevel"),
        "kind": event.get("kind"),
        "reviewSummary": event.get("reviewSummary"),
        "currentJob": event.get("currentJob"),
        "recoverable": event.get("recoverable"),
        "confirmation": event.get("confirmation"),
        "stats": event.get("stats"),
        "createdAt": event.get("createdAt") or _now(),
    }
    db[C.APPLICATION_EVENTS].insert_one(safe)
    return safe


def list_application_events(run_id: str, limit: int = 500) -> list[dict[str, Any]]:
    db = get_db()
    return list(
        db[C.APPLICATION_EVENTS]
        .find({"runId": run_id})
        .sort("sequence", 1)
        .limit(limit)
    )


def save_application_answer(payload: dict[str, Any]) -> dict[str, Any]:
    db = get_db()
    normalized = re.sub(
        r"\s+",
        " ",
        (payload.get("normalizedQuestion") or payload.get("question") or "")
        .strip()
        .lower(),
    )
    if not normalized:
        raise ValueError("normalizedQuestion required")
    answer_id = _slug_id("ans", normalized)
    doc = {
        "_id": answer_id,
        "normalizedQuestion": normalized,
        "answer": payload.get("answer"),
        "answerType": payload.get("answerType") or "TEXT",
        "source": payload.get("source") or "USER_CONFIRMED",
        "riskLevel": payload.get("riskLevel") or "MEDIUM",
        "allowedForAutofill": bool(payload.get("allowedForAutofill", False)),
        "reusePolicy": payload.get("reusePolicy") or "ONCE",
        "lastConfirmedAt": _now(),
        "updatedAt": _now(),
    }
    db[C.APPLICATION_ANSWERS].update_one(
        {"_id": answer_id}, {"$set": doc}, upsert=True
    )
    return doc


def candidate_agent_profile() -> dict[str, Any]:
    db = get_db()
    cand = db[C.CANDIDATES].find_one({"_id": "primary-candidate"}) or {}
    name = (cand.get("name") or "").strip()
    parts = name.split()

    # Latest role by startDate (seeded Capital One principal, etc.)
    roles = list(db[C.WORK_HISTORY].find({"candidateId": "primary-candidate"}))
    if not roles:
        roles = list(db[C.WORK_HISTORY].find({}))
    roles.sort(key=lambda r: str(r.get("startDate") or ""), reverse=True)
    latest = roles[0] if roles else None
    latest_role = None
    if latest:
        latest_role = {
            "title": latest.get("title"),
            "company": latest.get("company"),
            "startDate": latest.get("startDate"),
            "endDate": latest.get("endDate"),
            "companyLocation": latest.get("companyLocation"),
            "id": latest.get("_id"),
        }

    return {
        "fullName": name,
        "firstName": parts[0] if parts else "",
        "lastName": " ".join(parts[1:]) if len(parts) > 1 else "",
        "email": cand.get("email"),
        "phone": cand.get("phone"),
        "location": cand.get("location"),
        "linkedin": cand.get("linkedin"),
        "github": cand.get("github"),
        "minimumSalary": cand.get("minimumSalary"),
        "preferredLocations": cand.get("preferredLocations") or [],
        "remotePreference": cand.get("remotePreference"),
        "latestRole": latest_role,
    }
