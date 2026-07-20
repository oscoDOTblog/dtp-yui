"""Best-effort fetch of job listing pages for ingest enrichment."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib import error, request as urlrequest

from .gmail_source import html_to_text, resolve_redirect

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def fetch_listing_page(url: str, timeout: float = 8.0) -> dict[str, Any]:
    """Fetch a listing URL. Returns ok/blocked/text/finalUrl/titleHint."""
    url = (url or "").strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        return {
            "ok": False,
            "blocked": True,
            "fetchStatus": "blocked",
            "reason": "invalid url",
            "text": "",
            "finalUrl": url,
            "titleHint": "",
        }

    final_url = resolve_redirect(url, timeout=timeout)
    req = urlrequest.Request(
        final_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200) or 200
            raw = resp.read().decode("utf-8", errors="replace")
            final_url = resp.geturl() or final_url
    except error.HTTPError as exc:
        return {
            "ok": False,
            "blocked": True,
            "fetchStatus": "blocked",
            "reason": f"HTTP {exc.code}",
            "text": "",
            "finalUrl": final_url,
            "titleHint": "",
        }
    except Exception as exc:
        logger.debug("fetch_listing_page failed for %s: %s", url, exc)
        return {
            "ok": False,
            "blocked": True,
            "fetchStatus": "blocked",
            "reason": str(exc),
            "text": "",
            "finalUrl": final_url,
            "titleHint": "",
        }

    title_hint = ""
    og = re.search(
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
        raw,
        flags=re.I,
    )
    if og:
        title_hint = og.group(1).strip()
    else:
        title_tag = re.search(r"<title[^>]*>([\s\S]*?)</title>", raw, flags=re.I)
        if title_tag:
            title_hint = re.sub(r"\s+", " ", title_tag.group(1)).strip()

    text = html_to_text(raw)
    text = re.sub(r"\s+", " ", text).strip()[:12000]

    blocked_markers = (
        "captcha",
        "enable javascript",
        "sign in to continue",
        "log in to continue",
        "access denied",
        "unusual traffic",
        "authwall",
        "linkedin.com/login",
    )
    lower = text.lower()
    soft_block = any(m in lower for m in blocked_markers)
    too_short = len(text) < 280

    if status >= 400 or soft_block or too_short:
        return {
            "ok": False,
            "blocked": True,
            "fetchStatus": "blocked",
            "reason": "blocked or too short",
            "text": text if not soft_block else "",
            "finalUrl": final_url,
            "titleHint": title_hint,
        }

    return {
        "ok": True,
        "blocked": False,
        "fetchStatus": "ok",
        "reason": "",
        "text": text,
        "finalUrl": final_url,
        "titleHint": title_hint,
    }


def enrich_raw_job(raw: dict[str, Any]) -> dict[str, Any]:
    """Mutate/return raw job with resolved URL + fetched description when possible."""
    out = dict(raw)
    source_url = (out.get("sourceUrl") or out.get("canonicalApplyUrl") or "").strip()
    if not source_url:
        out["fetchStatus"] = "skipped"
        return out

    fetched = fetch_listing_page(source_url)
    final_url = fetched.get("finalUrl") or source_url
    out["sourceUrl"] = source_url
    out["canonicalApplyUrl"] = final_url
    out["url"] = final_url
    out["fetchStatus"] = fetched.get("fetchStatus") or "blocked"

    if fetched.get("ok") and fetched.get("text"):
        out["descriptionText"] = fetched["text"]
        title_hint = (fetched.get("titleHint") or "").strip()
        if title_hint and (
            not out.get("title")
            or out.get("title") in ("Untitled", "Unknown")
            or len(title_hint) > 8
        ):
            # Prefer page title when it looks like a role, not a site name
            if any(
                tok in title_hint.lower()
                for tok in ("engineer", "developer", "architect", "manager", "lead")
            ):
                # Often "Role - Company | Board"
                parts = re.split(r"\s+[|\-–—]\s+", title_hint)
                if parts:
                    out["title"] = parts[0].strip()[:120]
    else:
        # Keep card snippet; ensure description exists
        if not out.get("descriptionText"):
            out["descriptionText"] = (
                f"{out.get('company')} — {out.get('title')}\n"
                f"{out.get('location') or ''}\n"
                f"{final_url}"
            ).strip()

    return out
