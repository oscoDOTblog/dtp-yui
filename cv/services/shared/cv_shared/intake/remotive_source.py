"""Remotive public remote-jobs API adapter (global category poll, no watchlist)."""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib import error, parse, request as urlrequest

from ..settings import get_app_settings, ingest_drop_reason
from .html_markdown import description_fields_from_html_or_text, html_to_markdown
from .location import assess_location
from .role_filter import _title_is_ambiguous, assess_role_fit, load_role_filter_config

logger = logging.getLogger(__name__)

REMOTIVE_API = "https://remotive.com/api/remote-jobs"
DEFAULT_CATEGORY = "software-dev"
USER_AGENT = "CV-Job-Copilot/2C (+local; remotive remote-jobs poll)"
REQUEST_TIMEOUT_SEC = 45


def _location_from_job(job: dict[str, Any]) -> str:
    location = (job.get("candidate_required_location") or "").strip()
    if not location:
        return "Remote"
    if "remote" not in location.lower():
        return f"{location}, Remote"
    return location


def _title_is_ambiguous_for_early(title: str) -> bool:
    cfg = load_role_filter_config()
    ambiguous_tokens = [
        t.lower()
        for t in (cfg.get("ambiguousTitleTokens") or ["engineer", "developer"])
    ]
    return _title_is_ambiguous((title or "").lower().strip(), ambiguous_tokens)


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


def fetch_remotive_jobs(category: str = DEFAULT_CATEGORY) -> list[dict[str, Any]]:
    """GET public Remotive jobs for a category (full descriptions in one response)."""
    cat = (category or DEFAULT_CATEGORY).strip() or DEFAULT_CATEGORY
    qs = parse.urlencode({"category": cat})
    url = f"{REMOTIVE_API}?{qs}"
    payload = _http_get_json(url)
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        return []
    return [j for j in jobs if isinstance(j, dict)]


def early_keep_remotive_listing(
    job: dict[str, Any],
    *,
    app_settings: dict[str, Any] | None = None,
) -> tuple[bool, str | None]:
    """Prefilter using title + location (remote work mode)."""
    title = (job.get("title") or "").strip()
    location = _location_from_job(job)

    location_assessment = assess_location(
        location=location,
        title=title,
        description="",
        work_mode_hint="remote",
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


def remotive_job_to_raw(
    job: dict[str, Any],
    *,
    category: str = DEFAULT_CATEGORY,
) -> dict[str, Any]:
    job_id = job.get("id")
    job_id_str = str(job_id).strip() if job_id is not None else "unknown"
    job_url = (job.get("url") or "").strip()
    description_html = job.get("description") or ""
    fields = description_fields_from_html_or_text(description_html)
    description = (
        fields.get("descriptionText")
        or fields.get("descriptionRaw")
        or ""
    )
    description_md = fields.get("descriptionMarkdown") or html_to_markdown(
        description_html
    ) or None
    location = _location_from_job(job)
    company = (job.get("company_name") or "Unknown").strip() or "Unknown"

    return {
        "externalId": f"remotive:{job_id_str}",
        "source": "remotive",
        "title": (job.get("title") or "Untitled").strip(),
        "company": company,
        "location": location,
        "descriptionRaw": description,
        "descriptionText": description,
        "descriptionMarkdown": description_md,
        "sourceUrl": job_url or None,
        "canonicalApplyUrl": job_url or None,
        "url": job_url or None,
        "postedAt": job.get("publication_date"),
        "workMode": "remote",
        "salary": (job.get("salary") or "").strip() or None,
        "discoveredBy": {
            "source": "remotive",
            "category": category,
        },
    }


def fetch_remotive_raw_jobs(
    *,
    category: str = DEFAULT_CATEGORY,
    app_settings: dict[str, Any] | None = None,
    limit: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Poll Remotive remote-jobs API. Returns (raw_jobs, stats).

    Single-shot: list JSON includes descriptions; prefilter then map keepers.
    ``limit`` caps how many keepers to return (smoke tests / maxListings).
    """
    settings = app_settings if app_settings is not None else get_app_settings()
    cat = (category or DEFAULT_CATEGORY).strip() or DEFAULT_CATEGORY
    keep_limit = int(limit) if limit is not None and limit > 0 else None

    stats: dict[str, Any] = {
        "sourcesPolled": 0,
        "sourcesFailed": 0,
        "jobsListed": 0,
        "jobsPrefiltered": 0,
        "jobsFetched": 0,
        "skippedOutOfArea": 0,
        "skippedWrongRole": 0,
        "category": cat,
    }
    raw_jobs: list[dict[str, Any]] = []

    try:
        listed = fetch_remotive_jobs(category=cat)
        stats["jobsListed"] = len(listed)
        for job in listed:
            keep, reason = early_keep_remotive_listing(job, app_settings=settings)
            if not keep:
                stats["jobsPrefiltered"] += 1
                if reason == "outOfArea":
                    stats["skippedOutOfArea"] += 1
                elif reason == "wrongRole":
                    stats["skippedWrongRole"] += 1
                continue
            raw_jobs.append(remotive_job_to_raw(job, category=cat))
            if keep_limit is not None and len(raw_jobs) >= keep_limit:
                stats["truncatedToLimit"] = True
                break

        stats["sourcesPolled"] = 1
        stats["jobsFetched"] = len(raw_jobs)
    except error.HTTPError as exc:
        stats["sourcesFailed"] = 1
        msg = f"HTTP {exc.code}"
        logger.warning("Remotive poll failed: %s", msg)
        raise
    except Exception:
        stats["sourcesFailed"] = 1
        logger.exception("Remotive poll failed")
        raise

    return raw_jobs, stats


class RemotiveSource:
    """JobSource-compatible Remotive category poller."""

    name = "remotive"

    def __init__(self, category: str = DEFAULT_CATEGORY) -> None:
        self.category = category

    def fetch_jobs(self, since=None) -> list[dict[str, Any]]:  # noqa: ANN001
        raw, _stats = fetch_remotive_raw_jobs(category=self.category)
        return raw
