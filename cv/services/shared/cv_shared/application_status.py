"""Application pipeline status for job tracking (human decisions)."""

from __future__ import annotations

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
