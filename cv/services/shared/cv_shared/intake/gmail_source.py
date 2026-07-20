"""Parse job-alert email payloads into raw job dicts."""

from __future__ import annotations

import base64
import hashlib
import html
import logging
import re
from email.utils import parseaddr
from typing import Any
from urllib import error, request as urlrequest
from urllib.parse import parse_qs, unquote, urlparse

logger = logging.getLogger(__name__)

JOB_LINK_RE = re.compile(
    r"https?://[^\s<>\"']+(?:jobs|careers|greenhouse|lever|ashby|workday|indeed|linkedin|wellfound|builtin)[^\s<>\"']*",
    re.I,
)
GENERIC_LINK_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
TITLE_COMPANY_RE = re.compile(
    r"(?P<title>.+?)\s+(?:at|@|[-–—|])\s+(?P<company>.+)",
    re.I,
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
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clean_url(url: str) -> str:
    url = html.unescape(url).rstrip(").,;\"'")
    # Unwrap common redirectors
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        for key in ("url", "u", "q", "redirect"):
            if key in qs and qs[key]:
                candidate = unquote(qs[key][0])
                if candidate.startswith("http"):
                    return candidate
    except Exception:
        pass
    return url


def extract_links(text: str, html_body: str = "") -> list[str]:
    blob = f"{text}\n{html_body}"
    found = JOB_LINK_RE.findall(blob)
    if not found:
        found = GENERIC_LINK_RE.findall(blob)
    cleaned = []
    seen = set()
    for raw in found:
        url = _clean_url(raw)
        if any(
            skip in url.lower()
            for skip in (
                "unsubscribe",
                "mailto:",
                "preferences",
                "support.google",
                "accounts.google",
            )
        ):
            continue
        if url not in seen:
            seen.add(url)
            cleaned.append(url)
    return cleaned[:10]


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
    # LinkedIn-ish: "New jobs for Principal Software Engineer in San Francisco Bay Area"
    m = re.match(
        r"(?i)^(?:new jobs?(?: for)?|jobs? matching)\s+(.+?)(?:\s+in\s+.+)?$",
        subject,
    )
    if m:
        return m.group(1).strip(), "Unknown"

    m = TITLE_COMPANY_RE.search(subject)
    if m:
        return m.group("title").strip(), m.group("company").strip()

    # First non-empty body line
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
        r"Mountain View|Remote|Hybrid)[^\n,]{0,40}",
        body or "",
    )
    if m:
        return m.group(0).strip()
    return ""


def message_to_raw_jobs(message: dict) -> list[dict[str, Any]]:
    """Turn one Gmail message into one or more raw job dicts."""
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

    alert_source = detect_alert_source(from_header, subject)
    links = extract_links(text, html_body)
    title, company = parse_title_company(subject, text)
    location = extract_location_hint(subject, text)
    snippet = (message.get("snippet") or text[:800]).strip()

    if not links:
        # Still record a lead-like job from the email body
        external = f"gmail:{message_id}:body"
        return [
            {
                "externalId": external,
                "source": "gmail",
                "title": title,
                "company": company,
                "location": location,
                "descriptionText": text[:6000] or snippet,
                "sourceUrl": None,
                "canonicalApplyUrl": None,
                "discoveredBy": {
                    "source": alert_source,
                    "messageId": message_id,
                    "subject": subject,
                    "alertLocation": location or None,
                },
            }
        ]

    jobs = []
    for link in links[:5]:
        link_hash = hashlib.sha256(link.encode("utf-8")).hexdigest()[:12]
        resolved = resolve_redirect(link)
        jobs.append(
            {
                "externalId": f"gmail:{message_id}:{link_hash}",
                "source": "gmail",
                "title": title,
                "company": company,
                "location": location,
                "descriptionText": text[:6000] or snippet,
                "sourceUrl": link,
                "canonicalApplyUrl": resolved,
                "discoveredBy": {
                    "source": alert_source,
                    "messageId": message_id,
                    "subject": subject,
                    "alertLocation": location or None,
                },
            }
        )
    return jobs
