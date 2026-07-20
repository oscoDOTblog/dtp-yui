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
    r"Founding|Technical|Scientist|Designer|Analyst)[^$\n]{5,120}?)"
    r"(?:\n|\r|$)"
    r"(?P<location>[^\n$]{3,80})?",
    re.I | re.M,
)

CTA_ANCHOR_TEXTS = frozenset(
    {
        "easy apply",
        "apply",
        "see more jobs",
        "view job",
        "learn more",
        "apply now",
        "view all jobs",
    }
)

# Path/query noise — not applied to Glassdoor jobListing URLs
SKIP_URL_FRAGMENTS = (
    "unsubscribe",
    "mailto:",
    "preferences",
    "support.google",
    "accounts.google",
    "privacy",
    "settings",
    "create-alert",
    "createaler",
    "similar-jobs",
    "see-more",
    "facebook.com",
    "twitter.com",
    "instagram.com",
    "youtube.com",
)

# Extra noise only when not a clear job listing URL
SKIP_URL_FRAGMENTS_SOFT = (
    "/manage/",
    "manage-alert",
    "job-alert",
    "jobalert",
    "email-settings",
)

LOCATION_LINE_RE = re.compile(
    r"(?i)^\s*("
    r"Remote(?:\s*[-–]\s*[A-Za-z .]+)?|"
    r"Hybrid(?:\s*[-–]\s*[A-Za-z .]+)?|"
    r"Bay Area|"
    r"[A-Z][A-Za-z .'-]+,\s*[A-Z]{2}"
    r")\s*$"
)
SALARY_LINE_RE = re.compile(
    r"(?i)\$\s*[\d,]+(?:\.\d+)?\s*[Kk]?(?:\s*[-–—]\s*\$?\s*[\d,]+(?:\.\d+)?\s*[Kk]?)?"
    r"(?:\s*\([^)]*\))?"
)
RATING_SUFFIX_RE = re.compile(r"\s+\d\.\d\s*[★⭐]?\s*$")
JOB_LISTING_ID_RE = re.compile(r"(?i)(?:jobListingId|jl)=([0-9]+)")


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
    text = re.sub(r"(?i)</td>", "\n", text)
    text = re.sub(r"(?i)</div>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clean_url(url: str, depth: int = 0) -> str:
    """Unwrap nested redirect query params (url/u/q/redirect/dest)."""
    url = html.unescape(url or "").rstrip(").,;\"'")
    if depth > 4 or not url:
        return url
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        for key in ("url", "u", "q", "redirect", "dest", "continue"):
            if key in qs and qs[key]:
                candidate = unquote(qs[key][0])
                if candidate.startswith("http"):
                    return _clean_url(candidate, depth + 1)
    except Exception:
        pass
    return url


def _is_glassdoor_listing_url(url: str) -> bool:
    lower = (url or "").lower()
    if "glassdoor" not in lower:
        return False
    return any(
        tok in lower
        for tok in (
            "joblisting",
            "job-listing",
            "/job/",
            "partner/joblisting",
            "jl=",
            "joblistingid=",
        )
    )


def _is_noise_url(url: str) -> bool:
    lower = url.lower()
    if _is_glassdoor_listing_url(url):
        return False
    if any(skip in lower for skip in SKIP_URL_FRAGMENTS):
        return True
    return any(skip in lower for skip in SKIP_URL_FRAGMENTS_SOFT)


def _is_jobish_url(url: str) -> bool:
    lower = url.lower()
    if _is_noise_url(url):
        return False
    if _is_glassdoor_listing_url(url):
        return True
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
    if "glassdoor" in addr or "glassdoor" in subj:
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


def _strip_company_rating(text: str) -> str:
    cleaned = RATING_SUFFIX_RE.sub("", (text or "").strip())
    cleaned = re.sub(r"\s+\d\.\d\s*$", "", cleaned).strip()
    return cleaned[:80] if cleaned else "Unknown"


def _looks_like_company_line(line: str) -> bool:
    line = (line or "").strip()
    if not line or len(line) < 2 or len(line) > 80:
        return False
    if LOCATION_LINE_RE.match(line) or SALARY_LINE_RE.search(line):
        return False
    if line.lower() in CTA_ANCHOR_TEXTS:
        return False
    if line.startswith("http") or "@" in line:
        return False
    # Rating-only line
    if re.fullmatch(r"\d\.\d\s*[★⭐]?", line):
        return False
    return True


def _job_listing_id(url: str) -> str | None:
    m = JOB_LISTING_ID_RE.search(url or "")
    return m.group(1) if m else None


def extract_glassdoor_listings(
    html_body: str,
    *,
    alert_location: str = "",
) -> list[dict[str, Any]]:
    """Parse Glassdoor digest table cards: company, title link, location, salary."""
    if not html_body or "glassdoor" not in html_body.lower():
        return []

    lines = [
        ln.strip()
        for ln in html_to_text(html_body).splitlines()
        if ln.strip()
    ]

    # Collect title anchors with positions in raw HTML for ordering
    anchors: list[dict[str, Any]] = []
    for match in re.finditer(
        r'<a[^>]+href=["\'](https?://[^"\']+)["\'][^>]*>([\s\S]*?)</a>',
        html_body,
        flags=re.I,
    ):
        url = _clean_url(match.group(1))
        if not _is_glassdoor_listing_url(url):
            continue
        inner = re.sub(r"<[^>]+>", " ", match.group(2))
        inner = html.unescape(inner)
        inner = re.sub(r"\s+", " ", inner).strip()
        if len(inner) < 4:
            continue
        if inner.lower() in CTA_ANCHOR_TEXTS:
            continue
        # Skip image/logo-only (very short after strip already handled)
        anchors.append(
            {
                "url": url,
                "title": inner[:120],
                "start": match.start(),
                "listingId": _job_listing_id(url),
            }
        )

    if not anchors:
        return []

    # Dedupe by listingId or url, prefer longer title
    deduped: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for a in anchors:
        key = a["listingId"] or a["url"]
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(a)
        if len(deduped) >= PATHOLOGICAL_MAX:
            break

    listings: list[dict[str, Any]] = []
    for a in deduped:
        title = a["title"]
        # Find title line index in plain text
        title_idx = -1
        for i, line in enumerate(lines):
            if title in line or line in title:
                title_idx = i
                break
            # Fuzzy: same ignoring rating stars
            if line.lower() == title.lower():
                title_idx = i
                break

        company = "Unknown"
        location = ""
        salary = None

        if title_idx >= 0:
            # Company: look up 1–4 lines
            for j in range(title_idx - 1, max(-1, title_idx - 5), -1):
                cand = lines[j]
                # "Company 3.7 ★" on one line
                if RATING_SUFFIX_RE.search(cand) or re.search(r"\d\.\d\s*[★⭐]", cand):
                    company = _strip_company_rating(cand)
                    break
                if _looks_like_company_line(cand) and not re.search(
                    r"(?i)software|engineer|developer|manager|architect|stack",
                    cand,
                ):
                    company = _strip_company_rating(cand)
                    break
            # Location / salary: look down 1–5 lines
            for j in range(title_idx + 1, min(len(lines), title_idx + 6)):
                cand = lines[j]
                if not location and LOCATION_LINE_RE.match(cand):
                    location = cand.strip()[:80]
                    continue
                if salary is None and SALARY_LINE_RE.search(cand):
                    m = SALARY_LINE_RE.search(cand)
                    salary = m.group(0).strip()[:80] if m else None
                    continue
                if cand.lower() in CTA_ANCHOR_TEXTS:
                    continue
        else:
            # Fallback: scan text window near company+rating before title in lines
            for i, line in enumerate(lines):
                if RATING_SUFFIX_RE.search(line) or re.search(r"\d\.\d\s*[★⭐]", line):
                    maybe_co = _strip_company_rating(line)
                    # Next non-empty that looks like a title matching ours
                    for j in range(i + 1, min(len(lines), i + 4)):
                        if title.lower() in lines[j].lower() or lines[j].lower() in title.lower():
                            company = maybe_co
                            title_idx = j
                            break
                    if company != "Unknown":
                        for j in range(title_idx + 1, min(len(lines), title_idx + 6)):
                            cand = lines[j]
                            if not location and LOCATION_LINE_RE.match(cand):
                                location = cand.strip()[:80]
                            if salary is None and SALARY_LINE_RE.search(cand):
                                m = SALARY_LINE_RE.search(cand)
                                salary = m.group(0).strip()[:80] if m else None
                        break

        location = location or alert_location or ""
        snippet_parts = [f"{company} — {title}", location or "", salary or "", a["url"]]
        listings.append(
            {
                "title": title,
                "company": company,
                "location": location,
                "salary": salary,
                "url": a["url"],
                "listingId": a.get("listingId"),
                "cardSnippet": "\n".join(p for p in snippet_parts if p)[:2000],
            }
        )

    return listings


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
        if inner.lower() in CTA_ANCHOR_TEXTS:
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


def _listings_are_weak(listings: list[dict[str, Any]]) -> bool:
    if not listings:
        return True
    unknown = sum(1 for L in listings if (L.get("company") or "Unknown") == "Unknown")
    return unknown >= max(1, len(listings) // 2)


def extract_digest_listings(
    text: str,
    html_body: str,
    *,
    subject: str,
    alert_location: str,
    alert_source: str = "",
) -> list[dict[str, Any]]:
    """Return per-listing dicts with title/company/location/url/cardSnippet."""
    is_glassdoor = (
        alert_source == "glassdoor-email"
        or "glassdoor" in (html_body or "").lower()
        or "glassdoor" in (subject or "").lower()
    )

    if is_glassdoor:
        gd = extract_glassdoor_listings(html_body, alert_location=alert_location)
        if gd and not _listings_are_weak(gd):
            return gd
        if gd:
            # Prefer Glassdoor walker even if some companies unknown
            return gd

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

    if listings and not (is_glassdoor and _listings_are_weak(listings)):
        return listings

    if is_glassdoor:
        gd = extract_glassdoor_listings(html_body, alert_location=alert_location)
        if gd:
            return gd

    if listings:
        return listings

    # Fallback: links + subject/body heuristics
    links = extract_links(text, html_body)
    default_title, default_company = parse_title_company(subject, text)
    default_location = alert_location or extract_location_hint(subject, text)

    for url in links:
        loc = _location_near_url(text, url) or default_location
        title, company = default_title, default_company
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
        text = html_to_text(html_body) or text

    alert_source = detect_alert_source(from_header, subject)
    alert_location = extract_location_hint(subject, text)
    snippet = (message.get("snippet") or text[:800]).strip()

    listings = extract_digest_listings(
        text,
        html_body,
        subject=subject,
        alert_location=alert_location,
        alert_source=alert_source,
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
        listing_id = listing.get("listingId") or _job_listing_id(url)
        if listing_id:
            external = f"gmail:{message_id}:gd:{listing_id}"
        else:
            link_hash = hashlib.sha256(
                (
                    url or f"{listing.get('company')}|{listing.get('title')}|{idx}"
                ).encode("utf-8")
            ).hexdigest()[:12]
            external = f"gmail:{message_id}:{link_hash}"
        jobs.append(
            {
                "externalId": external,
                "source": "gmail",
                "title": listing.get("title") or "Untitled",
                "company": listing.get("company") or "Unknown",
                "location": listing.get("location") or alert_location or "",
                "salary": listing.get("salary"),
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
                    "listingId": listing_id,
                },
            }
        )
    return jobs
