"""Greenhouse Job Board API adapter for curated company watchlist."""

from __future__ import annotations

import html
import json
import logging
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib import error, parse, request as urlrequest

from .. import collections as C
from ..db import get_db
from ..settings import get_app_settings, ingest_drop_reason
from .html_markdown import html_to_markdown
from .location import assess_location
from .lookback import apply_board_lookback_and_order
from .role_filter import _title_is_ambiguous, assess_role_fit, load_role_filter_config

logger = logging.getLogger(__name__)

GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards"
USER_AGENT = "CV-Job-Copilot/2B (+local; greenhouse board poll)"
POLL_DELAY_SEC = 0.25
DETAIL_DELAY_SEC = 0.15
REQUEST_TIMEOUT_SEC = 30
# Cap detail fetches per board per poll (after prefilter)
MAX_DETAIL_FETCHES_PER_BOARD = 120


class _HTMLToText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("script", "style"):
            self._skip = True
        elif tag in ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4"):
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = False
        elif tag in ("p", "div", "li", "tr"):
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip and data:
            self._chunks.append(data)

    def text(self) -> str:
        joined = "".join(self._chunks)
        joined = html.unescape(joined)
        joined = re.sub(r"[ \t]+\n", "\n", joined)
        joined = re.sub(r"\n{3,}", "\n\n", joined)
        joined = re.sub(r"[ \t]{2,}", " ", joined)
        return joined.strip()


def html_to_text(raw_html: str | None) -> str:
    if not raw_html:
        return ""
    parser = _HTMLToText()
    try:
        parser.feed(raw_html)
        parser.close()
    except Exception:
        text = re.sub(r"<[^>]+>", " ", raw_html)
        return re.sub(r"\s+", " ", html.unescape(text)).strip()
    return parser.text()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        cleaned = value.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return None


def _http_get_json(url: str) -> Any:
    req = urlrequest.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    with urlrequest.urlopen(req, timeout=REQUEST_TIMEOUT_SEC) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def fetch_board_jobs(board_token: str, *, content: bool = True) -> list[dict[str, Any]]:
    """GET public Greenhouse board jobs. Raises on HTTP/network errors."""
    token = parse.quote((board_token or "").strip(), safe="")
    if not token:
        raise ValueError("boardToken is required")
    qs = "?content=true" if content else ""
    url = f"{GREENHOUSE_API}/{token}/jobs{qs}"
    payload = _http_get_json(url)
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        return []
    return jobs


def fetch_board_job(board_token: str, job_id: str | int) -> dict[str, Any]:
    """GET a single Greenhouse job post (includes content)."""
    token = parse.quote((board_token or "").strip(), safe="")
    jid = parse.quote(str(job_id).strip(), safe="")
    if not token or not jid:
        raise ValueError("boardToken and job_id are required")
    url = f"{GREENHOUSE_API}/{token}/jobs/{jid}"
    payload = _http_get_json(url)
    if not isinstance(payload, dict) or not payload.get("id"):
        raise ValueError(f"Greenhouse job {jid} missing id")
    return payload


def probe_board_token(board_token: str) -> dict[str, Any]:
    """Validate a board token with a lightweight list fetch (no content)."""
    try:
        jobs = fetch_board_jobs(board_token, content=False)
        return {"ok": True, "jobCount": len(jobs), "error": None}
    except error.HTTPError as exc:
        return {"ok": False, "jobCount": 0, "error": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"ok": False, "jobCount": 0, "error": str(exc)}


def _location_from_job(job: dict[str, Any]) -> str:
    loc = job.get("location") or {}
    if isinstance(loc, dict) and loc.get("name"):
        return str(loc["name"]).strip()
    offices = job.get("offices") or []
    names = []
    for office in offices:
        if isinstance(office, dict) and office.get("name"):
            names.append(str(office["name"]).strip())
    return ", ".join(names)


def _source_location_prefs(source: dict[str, Any]) -> list[str]:
    raw = source.get("locations") or []
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def _matches_source_locations(location: str, prefs: list[str]) -> bool:
    """If prefs set, require at least one substring match (case-insensitive)."""
    if not prefs:
        return True
    blob = (location or "").lower()
    if not blob:
        return False
    return any(pref.lower() in blob for pref in prefs)


def _title_is_ambiguous_for_early(title: str) -> bool:
    cfg = load_role_filter_config()
    ambiguous_tokens = [
        t.lower()
        for t in (cfg.get("ambiguousTitleTokens") or ["engineer", "developer"])
    ]
    return _title_is_ambiguous((title or "").lower().strip(), ambiguous_tokens)


def early_keep_greenhouse_listing(
    job: dict[str, Any],
    *,
    source: dict[str, Any],
    app_settings: dict[str, Any] | None = None,
) -> tuple[bool, str | None]:
    """Cheap prefilter using title + location only (no JD).

    Returns (keep, skip_reason) where skip_reason is for stats.
    """
    title = (job.get("title") or "").strip()
    location = _location_from_job(job)
    prefs = _source_location_prefs(source)

    if prefs and not _matches_source_locations(location, prefs):
        return False, "sourceLocation"

    # Build a stub normalized shape so ingest_drop_reason can apply
    location_assessment = assess_location(
        location=location,
        title=title,
        description="",
        work_mode_hint=None,
    )
    role_assessment = assess_role_fit(title=title, description="")

    # Ambiguous titles need JD for role gate — don't early-drop as wrong_role
    if (
        not role_assessment.get("roleEligible")
        and _title_is_ambiguous_for_early(title)
        and not role_assessment.get("matchedExcludes")
    ):
        role_assessment = {
            **role_assessment,
            "roleEligible": True,
            "evidence": list(role_assessment.get("evidence") or [])
            + ["early-filter: ambiguous title deferred to detail fetch"],
        }

    stub = {
        "status": "new",
        "title": title,
        "location": location,
        "locationAssessment": location_assessment,
        "roleAssessment": role_assessment,
    }
    if not location_assessment.get("bayAreaEligible"):
        stub["status"] = "out_of_area"
    elif not role_assessment.get("roleEligible"):
        stub["status"] = "wrong_role"

    # Normalize path also sets status; mirror for ingest_drop_reason
    drop = ingest_drop_reason(stub, app_settings)
    if drop == "outOfArea":
        return False, "outOfArea"
    if drop == "wrongRole":
        return False, "wrongRole"

    # Even when drop toggles are off, still apply source location prefs above
    return True, None


def greenhouse_job_to_raw(
    job: dict[str, Any],
    *,
    company: str,
    board_token: str,
    source_id: str,
) -> dict[str, Any]:
    job_id = job.get("id")
    absolute_url = (job.get("absolute_url") or "").strip()
    content_html = job.get("content") or ""
    description = html_to_text(content_html)
    description_md = html_to_markdown(content_html) or None
    location = _location_from_job(job)
    updated = job.get("updated_at") or job.get("created_at")

    return {
        "externalId": f"greenhouse:{board_token}:{job_id}",
        "source": "greenhouse",
        "title": (job.get("title") or "Untitled").strip(),
        "company": company,
        "location": location,
        "descriptionRaw": description,
        "descriptionText": description,
        "descriptionMarkdown": description_md,
        "sourceUrl": absolute_url or None,
        "canonicalApplyUrl": absolute_url or None,
        "url": absolute_url or None,
        "postedAt": updated,
        "discoveredBy": {
            "source": "greenhouse",
            "boardToken": board_token,
            "sourceId": source_id,
        },
    }


def _update_source_poll(
    source_id: str,
    *,
    success: bool,
    job_count: int | None = None,
    error_message: str | None = None,
    listed_count: int | None = None,
    prefiltered_count: int | None = None,
) -> None:
    now = _now()
    fields: dict[str, Any] = {
        "lastPolledAt": now,
        "updatedAt": now,
    }
    if success:
        fields["lastSuccessAt"] = now
        fields["lastError"] = None
        if job_count is not None:
            fields["lastJobCount"] = job_count
        if listed_count is not None:
            fields["lastListedCount"] = listed_count
        if prefiltered_count is not None:
            fields["lastPrefilteredCount"] = prefiltered_count
    else:
        fields["lastError"] = (error_message or "unknown error")[:500]
    get_db()[C.JOB_SOURCES].update_one({"_id": source_id}, {"$set": fields})


def list_enabled_greenhouse_sources() -> list[dict[str, Any]]:
    db = get_db()
    return list(
        db[C.JOB_SOURCES].find(
            {"ats": "greenhouse", "enabled": True},
            sort=[("priority", -1), ("name", 1)],
        )
    )


def _two_phase_enabled(app_settings: dict[str, Any] | None) -> bool:
    doc = app_settings if app_settings is not None else get_app_settings()
    filters = doc.get("ingestFilters") or {}
    if isinstance(filters, dict) and "greenhouseTwoPhase" in filters:
        return bool(filters["greenhouseTwoPhase"])
    return True


def fetch_greenhouse_raw_jobs(
    *,
    since: datetime | None = None,
    source_ids: list[str] | None = None,
    app_settings: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Poll enabled Greenhouse boards. Returns (raw_jobs, stats).

    Default two-phase flow:
      1) List jobs without content (cheap)
      2) Prefilter on title + location (+ source.locations)
      3) Fetch full JD only for keepers
    """
    db = get_db()
    settings = app_settings if app_settings is not None else get_app_settings()
    two_phase = _two_phase_enabled(settings)

    query: dict[str, Any] = {"ats": "greenhouse", "enabled": True}
    if source_ids:
        query["_id"] = {"$in": source_ids}

    sources = list(
        db[C.JOB_SOURCES].find(query, sort=[("priority", -1), ("name", 1)])
    )
    stats: dict[str, Any] = {
        "sourcesPolled": 0,
        "sourcesFailed": 0,
        "sourcesSkipped": 0,
        "jobsListed": 0,
        "jobsPrefiltered": 0,
        "jobsFetched": 0,
        "skippedOutOfArea": 0,
        "skippedWrongRole": 0,
        "skippedSourceLocation": 0,
        "skippedStale": 0,
        "detailFetchErrors": 0,
        "twoPhase": two_phase,
        "skippedOlderThanLookback": 0,
    }
    raw_jobs: list[dict[str, Any]] = []

    for idx, source in enumerate(sources):
        source_id = source["_id"]
        token = (source.get("boardToken") or "").strip()
        company = (source.get("name") or token).strip()
        if not token:
            stats["sourcesFailed"] += 1
            _update_source_poll(
                source_id, success=False, error_message="missing boardToken"
            )
            continue

        if idx > 0:
            time.sleep(POLL_DELAY_SEC)

        try:
            if not two_phase:
                board_jobs = fetch_board_jobs(token, content=True)
                mapped: list[dict[str, Any]] = []
                for job in board_jobs:
                    if since:
                        updated = _parse_iso(
                            job.get("updated_at") or job.get("created_at")
                        )
                        if updated and updated.tzinfo is None:
                            updated = updated.replace(tzinfo=timezone.utc)
                        if updated and updated < since:
                            stats["skippedStale"] += 1
                            continue
                    mapped.append(
                        greenhouse_job_to_raw(
                            job,
                            company=company,
                            board_token=token,
                            source_id=source_id,
                        )
                    )
                raw_jobs.extend(mapped)
                stats["sourcesPolled"] += 1
                stats["jobsListed"] += len(board_jobs)
                stats["jobsFetched"] += len(mapped)
                _update_source_poll(
                    source_id,
                    success=True,
                    job_count=len(mapped),
                    listed_count=len(board_jobs),
                    prefiltered_count=len(mapped),
                )
                continue

            # --- Two-phase ---
            listed = fetch_board_jobs(token, content=False)
            stats["jobsListed"] += len(listed)
            candidates: list[dict[str, Any]] = []
            for job in listed:
                if since:
                    updated = _parse_iso(job.get("updated_at") or job.get("created_at"))
                    if updated and updated.tzinfo is None:
                        updated = updated.replace(tzinfo=timezone.utc)
                    if updated and updated < since:
                        stats["skippedStale"] += 1
                        continue
                keep, reason = early_keep_greenhouse_listing(
                    job, source=source, app_settings=settings
                )
                if not keep:
                    stats["jobsPrefiltered"] += 1
                    if reason == "outOfArea":
                        stats["skippedOutOfArea"] += 1
                    elif reason == "wrongRole":
                        stats["skippedWrongRole"] += 1
                    elif reason == "sourceLocation":
                        stats["skippedSourceLocation"] += 1
                    continue
                candidates.append(job)

            if len(candidates) > MAX_DETAIL_FETCHES_PER_BOARD:
                logger.info(
                    "Greenhouse %s: capping detail fetches %s → %s",
                    token,
                    len(candidates),
                    MAX_DETAIL_FETCHES_PER_BOARD,
                )
                candidates = candidates[:MAX_DETAIL_FETCHES_PER_BOARD]

            mapped = []
            for detail_idx, stub in enumerate(candidates):
                job_id = stub.get("id")
                if job_id is None:
                    continue
                if detail_idx > 0:
                    time.sleep(DETAIL_DELAY_SEC)
                try:
                    full = fetch_board_job(token, job_id)
                except Exception as exc:
                    stats["detailFetchErrors"] += 1
                    logger.warning(
                        "Greenhouse detail fetch failed %s/%s: %s",
                        token,
                        job_id,
                        exc,
                    )
                    # Fall back to stub without JD so normalize can still run gates
                    full = stub
                mapped.append(
                    greenhouse_job_to_raw(
                        full,
                        company=company,
                        board_token=token,
                        source_id=source_id,
                    )
                )

            raw_jobs.extend(mapped)
            stats["sourcesPolled"] += 1
            stats["jobsFetched"] += len(mapped)
            _update_source_poll(
                source_id,
                success=True,
                job_count=len(mapped),
                listed_count=len(listed),
                prefiltered_count=len(candidates),
            )
        except error.HTTPError as exc:
            stats["sourcesFailed"] += 1
            msg = f"HTTP {exc.code}"
            logger.warning("Greenhouse poll failed for %s: %s", token, msg)
            _update_source_poll(source_id, success=False, error_message=msg)
        except Exception as exc:
            stats["sourcesFailed"] += 1
            logger.exception("Greenhouse poll failed for %s", token)
            _update_source_poll(source_id, success=False, error_message=str(exc))

    raw_jobs = apply_board_lookback_and_order(raw_jobs, stats)
    stats["jobsFetched"] = len(raw_jobs)
    return raw_jobs, stats


class GreenhouseBoardSource:
    """JobSource-compatible Greenhouse watchlist poller."""

    name = "greenhouse"

    def __init__(self, source_ids: list[str] | None = None) -> None:
        self.source_ids = source_ids

    def fetch_jobs(self, since: datetime | None = None) -> list[dict[str, Any]]:
        raw, _stats = fetch_greenhouse_raw_jobs(
            since=since, source_ids=self.source_ids
        )
        return raw
