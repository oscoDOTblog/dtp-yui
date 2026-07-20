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

logger = logging.getLogger(__name__)

GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards"
USER_AGENT = "CV-Job-Copilot/2B (+local; greenhouse board poll)"
POLL_DELAY_SEC = 0.25
REQUEST_TIMEOUT_SEC = 30


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
        # Fallback: crude tag strip
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


def fetch_board_jobs(board_token: str, *, content: bool = True) -> list[dict[str, Any]]:
    """GET public Greenhouse board jobs. Raises on HTTP/network errors."""
    token = parse.quote((board_token or "").strip(), safe="")
    if not token:
        raise ValueError("boardToken is required")
    qs = "?content=true" if content else ""
    url = f"{GREENHOUSE_API}/{token}/jobs{qs}"
    req = urlrequest.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    with urlrequest.urlopen(req, timeout=REQUEST_TIMEOUT_SEC) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    payload = json.loads(raw)
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        return []
    return jobs


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


def fetch_greenhouse_raw_jobs(
    *,
    since: datetime | None = None,
    source_ids: list[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Poll enabled Greenhouse boards. Returns (raw_jobs, stats)."""
    db = get_db()
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
        "jobsFetched": 0,
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
            board_jobs = fetch_board_jobs(token, content=True)
            mapped: list[dict[str, Any]] = []
            for job in board_jobs:
                if since:
                    updated = _parse_iso(job.get("updated_at") or job.get("created_at"))
                    if updated and updated.tzinfo is None:
                        updated = updated.replace(tzinfo=timezone.utc)
                    if updated and updated < since:
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
            stats["jobsFetched"] += len(mapped)
            _update_source_poll(
                source_id, success=True, job_count=len(mapped)
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
