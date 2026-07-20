"""Text normalization and job fingerprints for dedupe."""

from __future__ import annotations

import hashlib
import re


def normalize_text(value: str | None) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[&+/]", " ", text)
    text = re.sub(r"[^a-z0-9\s.-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def build_fingerprints(
    company: str | None,
    title: str | None,
    location: str | None,
) -> dict:
    company_n = normalize_text(company)
    title_n = normalize_text(title)
    location_n = normalize_text(location)
    exact_src = f"{company_n}|{title_n}|{location_n}"
    fuzzy_src = f"{company_n}|{title_n}"
    return {
        "exact": hashlib.sha256(exact_src.encode("utf-8")).hexdigest()[:32],
        "fuzzy": hashlib.sha256(fuzzy_src.encode("utf-8")).hexdigest()[:32],
        "exactKey": exact_src,
        "fuzzyKey": fuzzy_src,
    }
