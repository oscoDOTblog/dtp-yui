"""Text normalization and job fingerprints for dedupe."""

from __future__ import annotations

import hashlib
import re
from urllib import parse


def normalize_text(value: str | None) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[&+/]", " ", text)
    text = re.sub(r"[^a-z0-9\s.-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


_COMPANY_SUFFIX_RE = re.compile(
    r"\b(incorporated|inc|llc|l\.?l\.?c\.?|ltd|limited|corp|corporation|"
    r"co|company|plc|gmbh|ag|sa|s\.?a\.?|pty)\b\.?",
    re.I,
)
_TITLE_NOISE_RE = re.compile(
    r"\b(remote|hybrid|onsite|on[\s-]?site|work from home|wfh|"
    r"united states|usa|u\.s\.a?\.?|anywhere|worldwide)\b",
    re.I,
)
_TRACKING_QUERY_RE = re.compile(
    r"^(utm_|fbclid$|gclid$|mc_|ref$|source$|campaign$|medium$|_hs|"
    r"gh_jid$|gh_src$|ashby_jid$|lever-source$)",
    re.I,
)


def normalize_company_for_dedupe(company: str | None) -> str:
    text = normalize_text(company)
    text = _COMPANY_SUFFIX_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" .-")
    return text


def normalize_title_for_dedupe(title: str | None) -> str:
    text = normalize_text(title)
    # Drop parenthetical location / remote tags: "(Remote - US)"
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\[[^\]]*\]", " ", text)
    text = _TITLE_NOISE_RE.sub(" ", text)
    text = re.sub(r"\s*[-–—|]\s*$", "", text)
    text = re.sub(r"\s+", " ", text).strip(" .-")
    return text


def build_url_key(url: str | None) -> str | None:
    """Stable host+path key for the same apply/listing URL across trackers."""
    raw = (url or "").strip()
    if not raw:
        return None
    try:
        parsed = parse.urlparse(raw)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return None
    path = (parsed.path or "").rstrip("/") or "/"
    # Keep meaningful query ids (board job ids); drop tracking params
    kept: list[tuple[str, str]] = []
    if parsed.query:
        for key, value in parse.parse_qsl(parsed.query, keep_blank_values=False):
            if _TRACKING_QUERY_RE.search(key):
                continue
            key_l = key.lower()
            if key_l in (
                "id",
                "job_id",
                "jobid",
                "gh_jid",
                "application_id",
                "posting_id",
            ):
                kept.append((key_l, value.strip()))
        kept.sort()
    query = parse.urlencode(kept) if kept else ""
    src = f"{host}{path}"
    if query:
        src = f"{src}?{query}"
    return hashlib.sha256(src.encode("utf-8")).hexdigest()[:32]


def build_fingerprints(
    company: str | None,
    title: str | None,
    location: str | None,
) -> dict:
    company_n = normalize_company_for_dedupe(company)
    title_n = normalize_title_for_dedupe(title)
    location_n = normalize_text(location)
    exact_src = f"{company_n}|{title_n}|{location_n}"
    fuzzy_src = f"{company_n}|{title_n}"
    return {
        "exact": hashlib.sha256(exact_src.encode("utf-8")).hexdigest()[:32],
        "fuzzy": hashlib.sha256(fuzzy_src.encode("utf-8")).hexdigest()[:32],
        "exactKey": exact_src,
        "fuzzyKey": fuzzy_src,
    }
