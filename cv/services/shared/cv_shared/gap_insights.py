"""Aggregate recurring gap/warning requirements across job analyses."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from pymongo import ReturnDocument

from . import collections as C
from .db import get_db

logger = logging.getLogger(__name__)

ALIASES = {
    "k8s": "kubernetes",
    "js": "javascript",
    "ts": "typescript",
    "golang": "go",
    "node": "nodejs",
    "node.js": "nodejs",
    "react.js": "react",
    "next": "nextjs",
    "next.js": "nextjs",
    "postgres": "postgresql",
    "tf": "terraform",
    "aws lambda": "lambda",
    "amazon s3": "s3",
    "p4": "perforce",
    "perforce p4": "perforce",
    "elk": "elasticsearch",
    "llm": "llms",
}


def normalize_requirement(name: str) -> str:
    text = (name or "").strip().lower()
    text = re.sub(r"[_/]+", " ", text)
    text = re.sub(r"[^a-z0-9+.#\s-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return ALIASES.get(text, text)


def _gap_id(normalized: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_") or "unknown"
    return f"gap_{slug[:80]}"


def _items_from_match(match: dict) -> list[dict]:
    items = []
    for gap in match.get("meaningfulGaps") or []:
        name = gap.get("skill") or gap.get("requirement") or ""
        if not name:
            continue
        items.append(
            {
                "name": name,
                "kind": "gap",
                "severity": gap.get("severity") or "high",
                "reason": gap.get("reason") or "",
            }
        )
    for warn in match.get("warnings") or []:
        name = warn.get("skill") or warn.get("requirement") or ""
        if not name:
            continue
        items.append(
            {
                "name": name,
                "kind": "warning",
                "severity": warn.get("severity") or "warning",
                "reason": warn.get("reason") or "",
            }
        )
    return items


def record_gaps_from_match(match: dict, job: dict | None = None) -> int:
    """Upsert gap insights from a match. Counts once per jobId per requirement."""
    db = get_db()
    job = job or {}
    job_id = match.get("jobId") or job.get("_id")
    if not job_id:
        return 0

    now = datetime.now(timezone.utc).isoformat()
    touched = 0

    # Merge duplicate normalized names within one job (gap + warning both count kinds)
    merged: dict[str, dict] = {}
    for item in _items_from_match(match):
        normalized = normalize_requirement(item["name"])
        if not normalized:
            continue
        entry = merged.setdefault(
            normalized,
            {
                "display": (item.get("name") or "").strip() or normalized,
                "kinds": set(),
                "severities": set(),
                "reasons": [],
            },
        )
        entry["kinds"].add(item["kind"])
        entry["severities"].add(item["severity"])
        reason = (item.get("reason") or "").strip()
        if reason and reason not in entry["reasons"]:
            entry["reasons"].append(reason)
        display = (item.get("name") or "").strip()
        if display:
            entry["display"] = display

    for normalized, entry in merged.items():
        doc_id = _gap_id(normalized)
        existing = db[C.GAP_INSIGHTS].find_one({"_id": doc_id})
        recent = list(existing.get("recentJobIds") or []) if existing else []
        already_counted = job_id in recent

        if existing is None:
            kind_counts = {"gap": 0, "warning": 0}
            for kind in entry["kinds"]:
                kind_counts[kind] = 1
            severity_counts = {sev: 1 for sev in entry["severities"]}
            doc = {
                "_id": doc_id,
                "normalizedName": normalized,
                "displayName": entry["display"],
                "kindCounts": kind_counts,
                "severityCounts": severity_counts,
                "totalSeen": 1,
                "firstSeenAt": now,
                "lastSeenAt": now,
                "lastJobId": job_id,
                "lastJobTitle": job.get("title") or "",
                "lastCompany": job.get("company") or "",
                "recentJobIds": [job_id],
                "sampleReasons": entry["reasons"][:5],
                "status": "open",
            }
            db[C.GAP_INSIGHTS].insert_one(doc)
            touched += 1
            continue

        kind_counts = dict(existing.get("kindCounts") or {"gap": 0, "warning": 0})
        severity_counts = dict(existing.get("severityCounts") or {})
        total_seen = int(existing.get("totalSeen") or 0)
        sample_reasons = list(existing.get("sampleReasons") or [])

        if not already_counted:
            total_seen += 1
            for kind in entry["kinds"]:
                kind_counts[kind] = int(kind_counts.get(kind) or 0) + 1
            for sev in entry["severities"]:
                severity_counts[sev] = int(severity_counts.get(sev) or 0) + 1
            recent.append(job_id)
            recent = recent[-20:]

        for reason in entry["reasons"]:
            if reason and reason not in sample_reasons:
                sample_reasons.append(reason)
        sample_reasons = sample_reasons[-5:]

        db[C.GAP_INSIGHTS].update_one(
            {"_id": doc_id},
            {
                "$set": {
                    "displayName": entry["display"],
                    "kindCounts": kind_counts,
                    "severityCounts": severity_counts,
                    "totalSeen": total_seen,
                    "lastSeenAt": now,
                    "lastJobId": job_id,
                    "lastJobTitle": job.get("title") or existing.get("lastJobTitle") or "",
                    "lastCompany": job.get("company") or existing.get("lastCompany") or "",
                    "recentJobIds": recent,
                    "sampleReasons": sample_reasons,
                }
            },
        )
        touched += 1

    return touched


def list_gap_insights(kind: str = "all", status: str = "all") -> list[dict]:
    db = get_db()
    query: dict = {}
    if status and status != "all":
        query["status"] = status
    if kind == "gap":
        query["kindCounts.gap"] = {"$gt": 0}
    elif kind == "warning":
        query["kindCounts.warning"] = {"$gt": 0}

    insights = list(db[C.GAP_INSIGHTS].find(query))

    def sort_key(insight: dict) -> tuple[int, int]:
        counts = insight.get("kindCounts") or {}
        category_order = 0 if (counts.get("gap") or 0) > 0 else 1
        return category_order, -(insight.get("totalSeen") or 0)

    return sorted(insights, key=sort_key)


def update_gap_status(gap_id: str, status: str) -> dict | None:
    if status not in ("open", "learning", "resolved"):
        raise ValueError("status must be open|learning|resolved")
    db = get_db()
    return db[C.GAP_INSIGHTS].find_one_and_update(
        {"_id": gap_id},
        {
            "$set": {
                "status": status,
                "statusUpdatedAt": datetime.now(timezone.utc).isoformat(),
            }
        },
        return_document=ReturnDocument.AFTER,
    )


def remove_job_from_gap_insights(job_id: str, match: dict | None = None) -> int:
    """Remove a job's contribution from gap aggregates. Returns docs touched."""
    db = get_db()
    if not job_id:
        return 0

    touched = 0
    merged: dict[str, dict] = {}
    if match:
        for item in _items_from_match(match):
            normalized = normalize_requirement(item["name"])
            if not normalized:
                continue
            entry = merged.setdefault(
                normalized,
                {"kinds": set(), "severities": set()},
            )
            entry["kinds"].add(item["kind"])
            entry["severities"].add(item["severity"])

    # Always clear job refs from any gap that lists this job
    cursor = db[C.GAP_INSIGHTS].find(
        {
            "$or": [
                {"recentJobIds": job_id},
                {"lastJobId": job_id},
            ]
        }
    )
    for existing in cursor:
        doc_id = existing["_id"]
        recent = [jid for jid in (existing.get("recentJobIds") or []) if jid != job_id]
        was_counted = job_id in (existing.get("recentJobIds") or [])

        kind_counts = dict(existing.get("kindCounts") or {"gap": 0, "warning": 0})
        severity_counts = dict(existing.get("severityCounts") or {})
        total_seen = int(existing.get("totalSeen") or 0)

        normalized = existing.get("normalizedName") or ""
        entry = merged.get(normalized)
        if was_counted and entry:
            total_seen = max(0, total_seen - 1)
            for kind in entry["kinds"]:
                kind_counts[kind] = max(0, int(kind_counts.get(kind) or 0) - 1)
            for sev in entry["severities"]:
                severity_counts[sev] = max(0, int(severity_counts.get(sev) or 0) - 1)
        elif was_counted:
            total_seen = max(0, total_seen - 1)

        if total_seen <= 0 and not recent:
            db[C.GAP_INSIGHTS].delete_one({"_id": doc_id})
            touched += 1
            continue

        update_set = {
            "kindCounts": kind_counts,
            "severityCounts": severity_counts,
            "totalSeen": total_seen,
            "recentJobIds": recent,
        }
        if existing.get("lastJobId") == job_id:
            # Point last-seen at the most recent remaining job if possible
            last_id = recent[-1] if recent else None
            if last_id:
                job = db[C.JOBS].find_one({"_id": last_id}) or {}
                update_set["lastJobId"] = last_id
                update_set["lastJobTitle"] = job.get("title") or ""
                update_set["lastCompany"] = job.get("company") or ""
            else:
                update_set["lastJobId"] = None
                update_set["lastJobTitle"] = ""
                update_set["lastCompany"] = ""

        db[C.GAP_INSIGHTS].update_one({"_id": doc_id}, {"$set": update_set})
        touched += 1

    return touched


def rebuild_gap_insights() -> dict:
    """Clear aggregates and rebuild from all stored job matches (once per job)."""
    db = get_db()
    deleted = db[C.GAP_INSIGHTS].delete_many({}).deleted_count
    matches = list(db[C.JOB_MATCHES].find())
    jobs = {j["_id"]: j for j in db[C.JOBS].find()}
    touched = 0
    for match in matches:
        job = jobs.get(match.get("jobId")) or {}
        touched += record_gaps_from_match(match, job)
    return {
        "deleted": deleted,
        "matchesScanned": len(matches),
        "requirementsTouched": touched,
    }
