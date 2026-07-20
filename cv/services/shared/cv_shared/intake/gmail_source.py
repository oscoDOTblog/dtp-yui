"""Parse job-alert email payloads into per-listing raw job dicts."""

from __future__ import annotations

import base64
import hashlib
import html
import logging
import os
import re
from email.utils import parseaddr
from typing import Any
from urllib import request as urlrequest
from urllib.parse import parse_qs, unquote, urlparse

logger = logging.getLogger(__name__)

PATHOLOGICAL_MAX = int(os.environ.get("GMAIL_PATHOLOGICAL_MAX", "100"))

JOB_LINK_RE = re.compile(
    r"https?://[^\s<>\"']+(?:"
    r"jobs|careers|greenhouse|lever|ashby|workday|indeed|linkedin|"
    r"wellfound|builtin|glassdoor|jobvite|smartrecruiters"
    r")[^\s<>\"']*",
    re.I,
)
HREF_RE = re.compile(r'href=["\'](https?://[^"\']+)["\']', re.I)
GENERIC_LINK_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
TITLE_COMPANY_RE = re.compile(
    r"(?P<title>.+?)\s+(?:at|@|[-–—|])\s+(?P<company>.+)",
    re.I,
)
# Glassdoor/Indeed-ish: "Company  3.7 ★ Title" or "Company Title"
DIGEST_CARD_RE = re.compile(
    r"(?P<company>[A-Z][\w .,&'+-]{1,60}?)\s+"
    r"(?:\d\.\d\s*[★⭐]\s*)?"
    r"(?P<title>(?:Staff|Senior|Principal|Lead|Junior|Full[\s-]?Stack|"
    r"Software|Frontend|Front-End|Backend|Back-End|Platform|Cloud|"
    r"DevOps|SRE|Engineer|Developer|Architect|Manager|Director|"
    r"Founding|Technical)[^$\n]{5,120}?)"
    r"(?:\n|\r|$)"
    r"(?P<location>[^\n$]{3,80})?",
    re.I | re.M,
)

SKIP_URL_FRAGMENTS = (
    "unsubscribe",
    "mailto:",
    "preferences",
    "support.google",
    "accounts.google",
    "manage",
    "privacy",
    "settings",
    "create-alert",
    "createaler",
    "job-alert",
    "jobalert",
    "similar-jobs",
    "see-more",
    "facebook.com",
    "twitter.com",
    "instagram.com",
    "youtube.com",
)


def _b64url_decode(data: str) -> bytes:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8"))


def extract_bodies(payload: dict) -> tuple[str, str]:
    """Return (text, html) from a Gmail message payload."""
    text_parts: list[str] = []
    html_parts: list[str] = []

    def walk(part: dict) -> None:
        mime = (part.get("mimeType") or "").lower()
        body = part.get("body") or {}
        data = body.get("data")
        if data:
            try:
                decoded = _b64url_decode(data).decode("utf-8", errors="replace")
            except Exception:
                decoded = ""
            if mime == "text/plain":
                text_parts.append(decoded)
            elif mime == "text/html":
                html_parts.append(decoded)
        for child in part.get("parts") or []:
            walk(child)

    walk(payload or {})
    return ("\n".join(text_parts), "\n".join(html_parts))


def html_to_text(html_body: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html_body)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"(?i)</tr>", "\n", text)
    text = re.sub(r"(?i)</div>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clean_url(url: str) -> str:
    url = html.unescape(url).rstrip(").,;\"'")
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        for key in ("url", "u", "q", "redirect", "dest"):
            if key in qs and qs[key]:
                candidate = unquote(qs[key][0])
                if candidate.startswith("http"):
                    return candidate
    except Exception:
        pass
    return url


def _is_noise_url(url: str) -> bool:
    lower = url.lower()
    return any(skip in lower for skip in SKIP_URL_FRAGMENTS)


def _is_jobish_url(url: str) -> bool:
    lower = url.lower()
    if _is_noise_url(url):
        return False
    markers = (
        "job",
        "career",
        "greenhouse",
        "lever.co",
        "ashby",
        "workday",
        "indeed",
        "linkedin.com/jobs",
        "glassdoor",
        "wellfound",
        "builtin",
        "smartrecruiters",
        "jobvite",
    )
    return any(m in lower for m in markers)


def extract_links(text: str, html_body: str = "") -> list[str]:
    found: list[str] = []
    if html_body:
        found.extend(HREF_RE.findall(html_body))
    blob = f"{text}\n{html_body}"
    found.extend(JOB_LINK_RE.findall(blob))
    if not found:
        found.extend(GENERIC_LINK_RE.findall(blob))

    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in found:
        url = _clean_url(raw)
        if not _is_jobish_url(url):
            continue
        if url not in seen:
            seen.add(url)
            cleaned.append(url)
        if len(cleaned) >= PATHOLOGICAL_MAX:
            logger.warning(
                "Pathological link cap (%s) hit while extracting email links",
                PATHOLOGICAL_MAX,
            )
            break
    return cleaned


def resolve_redirect(url: str, timeout: float = 8.0) -> str:
    if not url:
        return url
    try:
        req = urlrequest.Request(
            url,
            method="GET",
            headers={
                "User-Agent": "Mozilla/5.0 CV-Job-Copilot/2A",
                "Accept": "text/html,*/*",
            },
        )
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            return resp.geturl() or url
    except Exception:
        return url


def detect_alert_source(from_header: str, subject: str) -> str:
    addr = parseaddr(from_header or "")[1].lower()
    subj = (subject or "").lower()
    if "linkedin" in addr or "linkedin" in subj:
        return "linkedin-email"
    if "indeed" in addr or "indeed" in subj:
        return "indeed-email"
    if "builtin" in addr or "built in" in subj:
        return "builtin-email"
    if "wellfound" in addr or "angelist" in addr or "angellist" in addr:
        return "wellfound-email"
    if "googlealerts" in addr or "google.com" in addr:
        return "google-alert"
    if "dice" in addr:
        return "dice-email"
    if "ziprecruiter" in addr:
        return "ziprecruiter-email"
    if "glassdoor" in addr:
        return "glassdoor-email"
    return "email-alert"


def parse_title_company(subject: str, body: str) -> tuple[str, str]:
    subject = (subject or "").strip()
    m = re.match(
        r"(?i)^(?:new jobs?(?: for)?|jobs? matching|job alert:?)\s+(.+?)(?:\s+in\s+.+)?$",
        subject,
    )
    if m:
        return m.group(1).strip(), "Unknown"

    m = TITLE_COMPANY_RE.search(subject)
    if m:
        return m.group("title").strip(), m.group("company").strip()

    for line in (body or "").splitlines():
        line = line.strip()
        if len(line) < 8 or line.lower().startswith("http"):
            continue
        m = TITLE_COMPANY_RE.search(line)
        if m:
            return m.group("title").strip()[:120], m.group("company").strip()[:120]
        if 8 <= len(line) <= 120:
            return line, "Unknown"
    return subject[:120] or "Untitled", "Unknown"


def extract_location_hint(subject: str, body: str) -> str:
    m = re.search(r"(?i)\bin\s+([A-Z][A-Za-z .,-]{2,60})$", (subject or "").strip())
    if m:
        return m.group(1).strip()
    m = re.search(
        r"(?i)\b(San Francisco|Oakland|Berkeley|Bay Area|San Jose|Palo Alto|"
        r"Mountain View|Remote|Hybrid|Sunnyvale|Daly City|San Bruno|"
        r"Brisbane|Emeryville)[^\n,]{0,40}",
        body or "",
    )
    if m:
        return m.group(0).strip()
    return ""


def _anchor_listings(html_body: str) -> list[dict[str, str]]:
    """Extract (url, anchor_text) pairs from HTML for digest cards."""
    listings: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in re.finditer(
        r'<a[^>]+href=["\'](https?://[^"\']+)["\'][^>]*>([\s\S]*?)</a>',
        html_body or "",
        flags=re.I,
    ):
        url = _clean_url(match.group(1))
        if not _is_jobish_url(url) or url in seen:
            continue
        inner = re.sub(r"<[^>]+>", " ", match.group(2))
        inner = html.unescape(inner)
        inner = re.sub(r"\s+", " ", inner).strip()
        if len(inner) < 6:
            continue
        # Skip pure CTA anchors
        if inner.lower() in (
            "easy apply",
            "apply",
            "see more jobs",
            "view job",
            "learn more",
        ):
            continue
        seen.add(url)
        listings.append({"url": url, "anchorText": inner[:200]})
        if len(listings) >= PATHOLOGICAL_MAX:
            break
    return listings


def _split_company_title(anchor: str) -> tuple[str, str]:
    text = (anchor or "").strip()
    # "Company 3.7 ★ Title"
    m = re.match(
        r"^(?P<company>.+?)\s+\d\.\d\s*[★⭐]\s*(?P<title>.+)$",
        text,
    )
    if m:
        return m.group("title").strip()[:120], m.group("company").strip()[:80]
    m = TITLE_COMPANY_RE.search(text)
    if m:
        return m.group("title").strip()[:120], m.group("company").strip()[:80]
    # Heuristic: last capital-run company words before engineer/developer titles
    m = re.match(
        r"^(?P<company>[A-Z][\w .,&'+-]{1,50}?)\s+"
        r"(?P<title>(?:Staff|Senior|Principal|Lead|Junior|Full[\s-]?Stack|"
        r"Software|Frontend|Backend|Platform|Engineer|Developer).+)$",
        text,
    )
    if m:
        return m.group("title").strip()[:120], m.group("company").strip()[:80]
    return text[:120] or "Untitled", "Unknown"


def _location_near_url(text: str, url: str) -> str:
    idx = text.find(url)
    window = text[max(0, idx - 200) : idx + 200] if idx >= 0 else text[:400]
    m = re.search(
        r"(?i)\b("
        r"San Francisco|Oakland|Berkeley|San Jose|Palo Alto|Mountain View|"
        r"Sunnyvale|Daly City|San Bruno|Brisbane|Emeryville|Remote|Hybrid|"
        r"Bay Area"
        r")(?:,\s*[A-Z]{2})?",
        window,
    )
    return m.group(0).strip() if m else ""


def extract_digest_listings(
    text: str,
    html_body: str,
    *,
    subject: str,
    alert_location: str,
) -> list[dict[str, Any]]:
    """Return per-listing dicts with title/company/location/url/cardSnippet."""
    listings: list[dict[str, Any]] = []

    for item in _anchor_listings(html_body):
        title, company = _split_company_title(item["anchorText"])
        location = _location_near_url(text, item["url"]) or alert_location
        snippet = (
            f"{company} — {title}\n{location}\n{item['anchorText']}".strip()
        )
        listings.append(
            {
                "title": title,
                "company": company,
                "location": location,
                "url": item["url"],
                "cardSnippet": snippet[:2000],
            }
        )

    if listings:
        return listings

    # Fallback: links + subject/body heuristics
    links = extract_links(text, html_body)
    default_title, default_company = parse_title_company(subject, text)
    default_location = alert_location or extract_location_hint(subject, text)

    for url in links:
        # Try to find nearby card text in plain body
        loc = _location_near_url(text, url) or default_location
        title, company = default_title, default_company
        # Look for DIGEST_CARD_RE blocks near the URL index
        idx = text.find(url)
        window = text[max(0, idx - 300) : idx] if idx >= 0 else ""
        m = DIGEST_CARD_RE.search(window)
        if m:
            company = m.group("company").strip()[:80]
            title = m.group("title").strip()[:120]
            if m.group("location"):
                loc = m.group("location").strip()[:80]
        listings.append(
            {
                "title": title,
                "company": company,
                "location": loc,
                "url": url,
                "cardSnippet": (
                    f"{company} — {title}\n{loc}\nSource: digest email"
                )[:2000],
            }
        )
        if len(listings) >= PATHOLOGICAL_MAX:
            break

    return listings


def message_to_raw_jobs(message: dict) -> list[dict[str, Any]]:
    """Turn one Gmail message into one or more raw job dicts (per listing)."""
    headers = {
        (h.get("name") or "").lower(): h.get("value") or ""
        for h in ((message.get("payload") or {}).get("headers") or [])
    }
    subject = headers.get("subject", "")
    from_header = headers.get("from", "")
    message_id = message.get("id") or ""
    text, html_body = extract_bodies(message.get("payload") or {})
    if not text and html_body:
        text = html_to_text(html_body)
    elif html_body:
        # Prefer richer line breaks from HTML for location pairing
        text = html_to_text(html_body) or text

    alert_source = detect_alert_source(from_header, subject)
    alert_location = extract_location_hint(subject, text)
    snippet = (message.get("snippet") or text[:800]).strip()

    listings = extract_digest_listings(
        text,
        html_body,
        subject=subject,
        alert_location=alert_location,
    )

    if not listings:
        external = f"gmail:{message_id}:body"
        title, company = parse_title_company(subject, text)
        return [
            {
                "externalId": external,
                "source": "gmail",
                "title": title,
                "company": company,
                "location": alert_location,
                "descriptionText": text[:6000] or snippet,
                "sourceUrl": None,
                "canonicalApplyUrl": None,
                "fetchStatus": "skipped",
                "discoveredBy": {
                    "source": alert_source,
                    "messageId": message_id,
                    "subject": subject,
                    "alertLocation": alert_location or None,
                    "digestIndex": 0,
                },
            }
        ]

    jobs: list[dict[str, Any]] = []
    for idx, listing in enumerate(listings):
        url = listing.get("url") or ""
        link_hash = hashlib.sha256(
            (url or f"{listing.get('company')}|{listing.get('title')}|{idx}").encode(
                "utf-8"
            )
        ).hexdigest()[:12]
        jobs.append(
            {
                "externalId": f"gmail:{message_id}:{link_hash}",
                "source": "gmail",
                "title": listing.get("title") or "Untitled",
                "company": listing.get("company") or "Unknown",
                "location": listing.get("location") or alert_location or "",
                "descriptionText": listing.get("cardSnippet") or snippet,
                "sourceUrl": url or None,
                "canonicalApplyUrl": url or None,
                "fetchStatus": "pending",
                "discoveredBy": {
                    "source": alert_source,
                    "messageId": message_id,
                    "subject": subject,
                    "alertLocation": alert_location or None,
                    "digestIndex": idx,
                },
            }
        )
    return jobs
