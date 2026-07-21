"""Convert a queued URL (or pasted description) into an intake raw job."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any
from urllib import error, parse, request as urlrequest

from .greenhouse_source import GREENHOUSE_API, greenhouse_job_to_raw

logger = logging.getLogger(__name__)

USER_AGENT = "CV-Job-Copilot/manual-queue (+local; single job fetch)"
REQUEST_TIMEOUT_SEC = 30

# boards.greenhouse.io/{token}/jobs/{id}
# job-boards.greenhouse.io/{token}/jobs/{id}
_GH_JOB_RE = re.compile(
    r"^https?://(?:job-)?boards\.greenhouse\.io/"
    r"(?P<token>[^/?#]+)/jobs/(?P<job_id>\d+)",
    flags=re.I,
)
# Some embeds use greenhouse.io/embed/job_app?token=…&for=board
_GH_EMBED_RE = re.compile(
    r"^https?://(?:www\.)?greenhouse\.io/embed/job_app",
    flags=re.I,
)


def parse_greenhouse_job_url(url: str) -> dict[str, str] | None:
    """Return {boardToken, jobId} if URL is a Greenhouse single-job page."""
    url = (url or "").strip()
    if not url:
        return None
    match = _GH_JOB_RE.match(url)
    if match:
        return {
            "boardToken": match.group("token").strip().lower(),
            "jobId": match.group("job_id"),
        }
    if _GH_EMBED_RE.match(url):
        parsed = parse.urlparse(url)
        qs = parse.parse_qs(parsed.query)
        token = (qs.get("for") or qs.get("board") or [None])[0]
        job_id = (qs.get("token") or qs.get("gh_jid") or qs.get("id") or [None])[0]
        if token and job_id and str(job_id).isdigit():
            return {"boardToken": str(token).strip().lower(), "jobId": str(job_id)}
    return None


def fetch_greenhouse_job(board_token: str, job_id: str) -> dict[str, Any]:
    """GET public Greenhouse single job with content HTML."""
    token = parse.quote((board_token or "").strip(), safe="")
    jid = parse.quote(str(job_id).strip(), safe="")
    url = f"{GREENHOUSE_API}/{token}/jobs/{jid}?content=true"
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
    if not isinstance(payload, dict) or not payload.get("id"):
        raise ValueError("Greenhouse job response missing id")
    return payload


def _company_from_board_token(board_token: str) -> str:
    token = (board_token or "").strip()
    if not token:
        return "Unknown"
    # Prefer watchlist name when available
    try:
        from .. import collections as C
        from ..db import get_db

        source = get_db()[C.JOB_SOURCES].find_one(
            {"ats": "greenhouse", "boardToken": token.lower()}
        )
        if source and source.get("name"):
            return str(source["name"]).strip()
    except Exception:
        logger.debug("boardToken company lookup failed", exc_info=True)
    return token.replace("-", " ").replace("_", " ").title()


def _manual_external_id(url: str, description: str) -> str:
    basis = (description or url or "").strip()
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
    return f"manual:{digest}"


def queue_item_to_raw(item: dict[str, Any]) -> dict[str, Any]:
    """
    Build a raw job dict for `_ingest_raw_jobs`.

    Sets ``_queueMeta``:
      - skipEnrich: bool — already has full content
      - needsPasteIfBlocked: bool — mark needsPaste when enrich fails
    """
    url = (item.get("url") or "").strip()
    paste = (item.get("descriptionRaw") or "").strip()
    queue_id = item.get("_id")

    gh = parse_greenhouse_job_url(url)
    if gh:
        try:
            job = fetch_greenhouse_job(gh["boardToken"], gh["jobId"])
            company = _company_from_board_token(gh["boardToken"])
            source_id = f"manual_queue:{queue_id or 'unknown'}"
            raw = greenhouse_job_to_raw(
                job,
                company=company,
                board_token=gh["boardToken"],
                source_id=source_id,
            )
            raw["discoveredBy"] = {
                **(raw.get("discoveredBy") or {}),
                "source": "manual-queue",
                "queueId": queue_id,
                "boardToken": gh["boardToken"],
            }
            # Prefer the user-pasted URL as sourceUrl when API absolute_url missing
            if not raw.get("sourceUrl"):
                raw["sourceUrl"] = url
                raw["canonicalApplyUrl"] = url
                raw["url"] = url
            raw["_queueMeta"] = {
                "queueId": queue_id,
                "skipEnrich": True,
                "needsPasteIfBlocked": False,
            }
            return raw
        except error.HTTPError as exc:
            logger.warning(
                "Greenhouse single-job fetch HTTP %s for %s", exc.code, url
            )
            if paste:
                return _raw_from_paste(url, paste, queue_id)
            # Fall through to stub — enrich may still work on the HTML page
        except Exception as exc:
            logger.warning("Greenhouse single-job fetch failed for %s: %s", url, exc)
            if paste:
                return _raw_from_paste(url, paste, queue_id)

    if paste:
        return _raw_from_paste(url, paste, queue_id)

    # Stub for enrich_raw_job in the pipeline
    return {
        "externalId": _manual_external_id(url, ""),
        "source": "manual",
        "title": "Untitled",
        "company": "Unknown",
        "location": "",
        "descriptionRaw": "",
        "descriptionText": "",
        "sourceUrl": url or None,
        "canonicalApplyUrl": url or None,
        "url": url or None,
        "discoveredBy": {"source": "manual-queue", "queueId": queue_id},
        "_queueMeta": {
            "queueId": queue_id,
            "skipEnrich": False,
            "needsPasteIfBlocked": True,
        },
    }


def _raw_from_paste(url: str, paste: str, queue_id: Any) -> dict[str, Any]:
    return {
        "externalId": _manual_external_id(url, paste),
        "source": "manual",
        "title": "Untitled",
        "company": "Unknown",
        "location": "",
        "descriptionRaw": paste,
        "descriptionText": paste,
        "sourceUrl": url or None,
        "canonicalApplyUrl": url or None,
        "url": url or None,
        "fetchStatus": "pasted",
        "discoveredBy": {"source": "manual-queue", "queueId": queue_id},
        "_queueMeta": {
            "queueId": queue_id,
            "skipEnrich": True,
            "needsPasteIfBlocked": False,
        },
    }


def is_enrich_blocked_or_empty(enriched: dict[str, Any]) -> bool:
    """True when we should ask the user to paste instead of creating a hollow job."""
    text = (enriched.get("descriptionText") or enriched.get("descriptionRaw") or "").strip()
    fetch_status = (enriched.get("fetchStatus") or "").strip()
    if fetch_status == "blocked":
        return True
    if len(text) < 280:
        return True
    # Hollow stub left over from blocked enrich fallback
    if text.count("\n") <= 2 and "http" in text.lower() and len(text) < 400:
        title = (enriched.get("title") or "").strip()
        company = (enriched.get("company") or "").strip()
        if title in ("", "Untitled") and company in ("", "Unknown"):
            return True
    return False
