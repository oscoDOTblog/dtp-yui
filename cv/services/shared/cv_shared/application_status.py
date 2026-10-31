"""Application pipeline status for job tracking (human decisions)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

# Ordered interview track (Rejected is terminal / off-rail)
APPLICATION_STATUS_ORDER = (
    "apply",
    "pending",
    "round1",
    "round2",
    "round3",
    "round4",
)

APPLICATION_STATUSES = APPLICATION_STATUS_ORDER + ("rejected",)

# Pipeline stages that mean the candidate has submitted an application.
# `pending` is the first applied stage; later rounds inherit the original apply.
APPLIED_PIPELINE_STATUSES = frozenset(
    ("pending", "round1", "round2", "round3", "round4")
)

APPLICATION_STATUS_LABELS = {
    "apply": "Apply",
    "pending": "Pending",
    "round1": "Round 1",
    "round2": "Round 2",
    "round3": "Round 3",
    "round4": "Round 4",
    "rejected": "Rejected",
}


def marks_applied(status: str | None) -> bool:
    """True when setting this status should record an application (appliedAt)."""
    return status in APPLIED_PIPELINE_STATUSES

# Legacy decision / job.status values → pipeline status
_LEGACY_DECISION_MAP = {
    "apply": "apply",
    "save": "pending",
    "reject": "rejected",
    "interested": "apply",
    "saved": "pending",
    "rejected": "rejected",
    "draft": "apply",
    "drafted": "apply",
}


def normalize_application_status(raw: str | None) -> str | None:
    """Return a canonical applicationStatus or None if unknown/empty."""
    if raw is None:
        return None
    value = str(raw).strip().lower().replace(" ", "").replace("_", "")
    # round 1 → round1
    if value.startswith("round") and len(value) > 5:
        value = "round" + value[5:]
    aliases = {
        "r1": "round1",
        "r2": "round2",
        "r3": "round3",
        "r4": "round4",
        **{k.replace("_", ""): v for k, v in _LEGACY_DECISION_MAP.items()},
    }
    if value in APPLICATION_STATUSES:
        return value
    if value in aliases:
        return aliases[value]
    return None


def resolve_application_status(job: dict | None) -> str | None:
    """Prefer explicit applicationStatus; fall back to legacy status/decision."""
    if not job:
        return None
    explicit = normalize_application_status(job.get("applicationStatus"))
    if explicit:
        return explicit
    return normalize_application_status(job.get("status"))


# Jobs sitting in an applied pipeline stage with no update for this long are
# treated as gone quiet and auto-transitioned to "rejected" on /applications.
STALE_APPLICATION_DAYS = 14

STALE_AUTO_REJECT_NOTE = "Auto-rejected after 14 days without an update"


def parse_status_timestamp(value: Any) -> datetime | None:
    """Parse an applicationStatusAt/updatedAt value into aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def last_application_update(job: dict | None) -> datetime | None:
    """Most recent of applicationStatusAt / updatedAt, or None if unknown."""
    if not job:
        return None
    moments = [
        parse_status_timestamp(job.get("applicationStatusAt")),
        parse_status_timestamp(job.get("updatedAt")),
    ]
    moments = [m for m in moments if m is not None]
    return max(moments) if moments else None


def is_application_stale(
    job: dict | None,
    now: datetime | None = None,
    *,
    stale_after_days: int = STALE_APPLICATION_DAYS,
) -> bool:
    """True when an applied job has had no update for at least the window."""
    if resolve_application_status(job) not in APPLIED_PIPELINE_STATUSES:
        return False
    last = last_application_update(job)
    if last is None:
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return (current - last) >= timedelta(days=stale_after_days)


def auto_reject_stale_applications(
    db,
    now: datetime | None = None,
    *,
    stale_after_days: int = STALE_APPLICATION_DAYS,
) -> int:
    """Flip applied jobs idle for the window to rejected. Returns the count."""
    from . import collections as C

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    now_iso = current.isoformat()

    # Timestamps are stored as ISO strings, so the age check runs in Python;
    # the query only narrows to plausible pipeline candidates.
    candidates = list(
        db[C.JOBS].find(
            {
                "$or": [
                    {"applicationStatus": {"$in": sorted(APPLIED_PIPELINE_STATUSES)}},
                    {"status": {"$in": ["saved", "interview"]}},
                ]
            }
        )
    )

    expired = 0
    for job in candidates:
        if not is_application_stale(
            job, now=current, stale_after_days=stale_after_days
        ):
            continue
        job_id = job["_id"]
        fields: dict[str, Any] = {
            "applicationStatus": "rejected",
            "applicationStatusAt": now_iso,
            "updatedAt": now_iso,
        }
        # Same intake-gate guard as a manual status change.
        if (job.get("status") or "").strip() not in ("out_of_area", "wrong_role"):
            fields["status"] = "rejected"
        db[C.JOBS].update_one({"_id": job_id}, {"$set": fields})

        db[C.APPLICATIONS].update_one(
            {"_id": f"app_{job_id}"},
            {
                "$set": {
                    "jobId": job_id,
                    "status": "rejected",
                    "updatedAt": now_iso,
                },
                "$setOnInsert": {"_id": f"app_{job_id}"},
            },
            upsert=True,
        )

        db[C.USER_DECISIONS].insert_one(
            {
                "_id": f"decision_{job_id}_{int(current.timestamp())}",
                "jobId": job_id,
                "decision": "rejected",
                "applicationStatus": "rejected",
                "label": APPLICATION_STATUS_LABELS.get("rejected", "rejected"),
                "note": STALE_AUTO_REJECT_NOTE,
                "createdAt": now_iso,
            }
        )
        expired += 1
    return expired
