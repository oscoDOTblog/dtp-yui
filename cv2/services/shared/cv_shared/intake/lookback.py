"""Board ingest lookback: keep recent postings, prefer unprocessed first."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import collections as C
from ..db import get_db
from .upsert import job_posting_dt

logger = logging.getLogger(__name__)

DEFAULT_BOARD_LOOKBACK_DAYS = 14
ANALYZED_STATUSES = frozenset({"analyzed", "drafted"})


def board_lookback_days() -> int:
    try:
        return max(
            1,
            int(
                os.environ.get(
                    "INGEST_BOARD_LOOKBACK_DAYS", DEFAULT_BOARD_LOOKBACK_DAYS
                )
            ),
        )
    except ValueError:
        return DEFAULT_BOARD_LOOKBACK_DAYS


def posting_within_board_lookback(
    raw: dict[str, Any],
    *,
    days: int | None = None,
    now: datetime | None = None,
) -> bool:
    """True when postedAt is missing (keep) or within the lookback window."""
    window = days if days is not None else board_lookback_days()
    # Prefer explicit postedAt only — firstSeen on re-fetch would always be "now"
    posted = job_posting_dt({"postedAt": raw.get("postedAt")})
    if posted is None:
        return True
    clock = now or datetime.now(timezone.utc)
    return posted >= clock - timedelta(days=window)


def _existing_job_meta(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Cheap lookup: externalId → altExternalIds → urlKey."""
    db = get_db()
    external_id = (raw.get("externalId") or "").strip()
    if external_id:
        hit = db[C.JOBS].find_one(
            {"externalId": external_id},
            {"_id": 1, "status": 1, "postedAt": 1},
        )
        if hit:
            return hit
        hit = db[C.JOBS].find_one(
            {"altExternalIds": external_id},
            {"_id": 1, "status": 1, "postedAt": 1},
        )
        if hit:
            return hit
    url_key = (raw.get("urlKey") or "").strip()
    if url_key:
        hit = db[C.JOBS].find_one(
            {"urlKey": url_key},
            {"_id": 1, "status": 1, "postedAt": 1},
        )
        if hit:
            return hit
    return None


def _priority_key(
    raw: dict[str, Any],
    existing: dict[str, Any] | None,
) -> tuple[int, float]:
    """Sort key: unprocessed first, then not-yet-scored, then newest postedAt."""
    if existing is None:
        tier = 0  # brand new to inbox
    elif (existing.get("status") or "") not in ANALYZED_STATUSES:
        tier = 1  # known but not scored yet
    else:
        tier = 2  # already analyzed / drafted — deprioritize
    posted = job_posting_dt(raw) or job_posting_dt(existing)
    # Negative timestamp → newest first within tier
    ts = -(posted.timestamp()) if posted else 0.0
    return (tier, ts)


def apply_board_lookback_and_order(
    raw_jobs: list[dict[str, Any]],
    stats: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Drop postings older than lookback; order unprocessed first, then newest.

    Mutates ``stats`` when provided (skippedOlderThanLookback, boardLookbackDays).
    """
    days = board_lookback_days()
    now = datetime.now(timezone.utc)
    if stats is not None:
        stats["boardLookbackDays"] = days

    kept: list[dict[str, Any]] = []
    skipped_old = 0
    for raw in raw_jobs:
        if not posting_within_board_lookback(raw, days=days, now=now):
            skipped_old += 1
            continue
        kept.append(raw)

    if stats is not None:
        stats["skippedOlderThanLookback"] = (
            int(stats.get("skippedOlderThanLookback") or 0) + skipped_old
        )

    if not kept:
        return []

    # Batch priority with DB probes (ok for board-sized lists after early filters)
    decorated: list[tuple[tuple[int, float], dict[str, Any]]] = []
    for raw in kept:
        existing = _existing_job_meta(raw)
        decorated.append((_priority_key(raw, existing), raw))
    decorated.sort(key=lambda item: item[0])
    return [raw for _, raw in decorated]
