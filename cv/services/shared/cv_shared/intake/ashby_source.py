"""Ashby public Job Postings API adapter for curated company watchlist."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any
from urllib import error, parse, request as urlrequest

from .. import collections as C
from ..db import get_db
from ..settings import get_app_settings, ingest_drop_reason
from .html_markdown import description_fields_from_html_or_text, html_to_markdown
from .location import assess_location
from .role_filter import _title_is_ambiguous, assess_role_fit, load_role_filter_config

logger = logging.getLogger(__name__)

ASHBY_API = "https://api.ashbyhq.com/posting-api/job-board"
USER_AGENT = "CV-Job-Copilot/2C (+local; ashby board poll)"
POLL_DELAY_SEC = 0.25
REQUEST_TIMEOUT_SEC = 30


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


def fetch_board_jobs(
    board_token: str, *, include_compensation: bool = True
) -> list[dict[str, Any]]:
    """GET public Ashby board jobs (full descriptions in one response)."""
    token = parse.quote((board_token or "").strip(), safe="")
    if not token:
        raise ValueError("boardToken is required")
    qs = "?includeCompensation=true" if include_compensation else ""
    url = f"{ASHBY_API}/{token}{qs}"
    payload = _http_get_json(url)
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        return []
    return jobs


def probe_board_token(board_token: str) -> dict[str, Any]:
    """Validate a board slug with a board list fetch."""
    try:
        jobs = fetch_board_jobs(board_token, include_compensation=False)
        return {"ok": True, "jobCount": len(jobs), "error": None}
    except error.HTTPError as exc:
        return {"ok": False, "jobCount": 0, "error": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"ok": False, "jobCount": 0, "error": str(exc)}


def _secondary_location_names(job: dict[str, Any]) -> list[str]:
    names: list[str] = []
    secondary = job.get("secondaryLocations") or []
    if not isinstance(secondary, list):
        return names
    for item in secondary:
        if isinstance(item, dict) and item.get("location"):
            names.append(str(item["location"]).strip())
        elif isinstance(item, str) and item.strip():
            names.append(item.strip())
    return names


def _location_from_job(job: dict[str, Any]) -> str:
    parts: list[str] = []
    primary = (job.get("location") or "").strip()
    if primary:
        parts.append(primary)
    for name in _secondary_location_names(job):
        if name and name not in parts:
            parts.append(name)
    if job.get("isRemote") and "remote" not in " ".join(parts).lower():
        parts.append("Remote")
    return ", ".join(parts)


def _work_mode_hint(job: dict[str, Any]) -> str | None:
    workplace = (job.get("workplaceType") or "").strip().lower()
    if workplace == "remote" or job.get("isRemote"):
        return "remote"
    if workplace == "hybrid":
        return "hybrid"
    if workplace in ("onsite", "on-site", "on_site"):
        return "onsite"
    return None


def _job_id(job: dict[str, Any]) -> str:
    raw_id = job.get("id")
    if raw_id is not None and str(raw_id).strip():
        return str(raw_id).strip()
    job_url = (job.get("jobUrl") or job.get("applyUrl") or "").strip()
    if job_url:
        path = parse.urlparse(job_url).path.strip("/")
        segments = [s for s in path.split("/") if s]
        # jobs.ashbyhq.com/{org}/{id} or …/{id}/application
        for seg in reversed(segments):
            if seg.lower() in ("application", "apply"):
                continue
            if len(seg) >= 8:
                return seg
    return ""


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


def early_keep_ashby_listing(
    job: dict[str, Any],
    *,
    source: dict[str, Any],
    app_settings: dict[str, Any] | None = None,
) -> tuple[bool, str | None]:
    """Prefilter using title + location (+ secondary / remote hints)."""
    if job.get("isListed") is False:
        return False, "unlisted"

    title = (job.get("title") or "").strip()
    location = _location_from_job(job)
    prefs = _source_location_prefs(source)

    if prefs and not _matches_source_locations(location, prefs):
        return False, "sourceLocation"

    location_assessment = assess_location(
        location=location,
        title=title,
        description="",
        work_mode_hint=_work_mode_hint(job),
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
            + ["early-filter: ambiguous title deferred to full JD"],
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

    drop = ingest_drop_reason(stub, app_settings)
    if drop == "outOfArea":
        return False, "outOfArea"
    if drop == "wrongRole":
        return False, "wrongRole"

    return True, None


def ashby_job_to_raw(
    job: dict[str, Any],
    *,
    company: str,
    board_token: str,
    source_id: str,
) -> dict[str, Any]:
    job_id = _job_id(job) or "unknown"
    job_url = (job.get("jobUrl") or "").strip()
    apply_url = (job.get("applyUrl") or job_url).strip()
    description_html = job.get("descriptionHtml") or ""
    description_plain = (job.get("descriptionPlain") or "").strip()
    fields = description_fields_from_html_or_text(
        description_html or description_plain
    )
    description = (
        description_plain
        or fields.get("descriptionText")
        or fields.get("descriptionRaw")
        or ""
    )
    description_md = fields.get("descriptionMarkdown") or html_to_markdown(
        description_html
    ) or None
    location = _location_from_job(job)
    published = job.get("publishedAt")
    work_mode = _work_mode_hint(job)

    return {
        "externalId": f"ashby:{board_token}:{job_id}",
        "source": "ashby",
        "title": (job.get("title") or "Untitled").strip(),
        "company": company,
        "location": location,
        "descriptionRaw": description,
        "descriptionText": description,
        "descriptionMarkdown": description_md,
        "sourceUrl": job_url or apply_url or None,
        "canonicalApplyUrl": apply_url or job_url or None,
        "url": job_url or apply_url or None,
        "postedAt": published,
        "workMode": work_mode,
        "discoveredBy": {
            "source": "ashby",
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


def list_enabled_ashby_sources() -> list[dict[str, Any]]:
    db = get_db()
    return list(
        db[C.JOB_SOURCES].find(
            {"ats": "ashby", "enabled": True},
            sort=[("priority", -1), ("name", 1)],
        )
    )


def fetch_ashby_raw_jobs(
    *,
    since: datetime | None = None,
    source_ids: list[str] | None = None,
    app_settings: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Poll enabled Ashby boards. Returns (raw_jobs, stats).

    Single-shot: board JSON includes descriptions; prefilter then map keepers.
    """
    db = get_db()
    settings = app_settings if app_settings is not None else get_app_settings()

    query: dict[str, Any] = {"ats": "ashby", "enabled": True}
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
        "skippedUnlisted": 0,
        "skippedStale": 0,
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
            listed = fetch_board_jobs(token, include_compensation=True)
            stats["jobsListed"] += len(listed)
            mapped: list[dict[str, Any]] = []
            kept = 0
            for job in listed:
                if since:
                    updated = _parse_iso(job.get("publishedAt"))
                    if updated and updated.tzinfo is None:
                        updated = updated.replace(tzinfo=timezone.utc)
                    if updated and updated < since:
                        stats["skippedStale"] += 1
                        continue
                keep, reason = early_keep_ashby_listing(
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
                    elif reason == "unlisted":
                        stats["skippedUnlisted"] += 1
                    continue
                kept += 1
                mapped.append(
                    ashby_job_to_raw(
                        job,
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
                prefiltered_count=kept,
            )
        except error.HTTPError as exc:
            stats["sourcesFailed"] += 1
            msg = f"HTTP {exc.code}"
            logger.warning("Ashby poll failed for %s: %s", token, msg)
            _update_source_poll(source_id, success=False, error_message=msg)
        except Exception as exc:
            stats["sourcesFailed"] += 1
            logger.exception("Ashby poll failed for %s", token)
            _update_source_poll(source_id, success=False, error_message=str(exc))

    return raw_jobs, stats


class AshbyBoardSource:
    """JobSource-compatible Ashby watchlist poller."""

    name = "ashby"

    def __init__(self, source_ids: list[str] | None = None) -> None:
        self.source_ids = source_ids

    def fetch_jobs(self, since: datetime | None = None) -> list[dict[str, Any]]:
        raw, _stats = fetch_ashby_raw_jobs(since=since, source_ids=self.source_ids)
        return raw
