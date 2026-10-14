"""Bay Area / work-arrangement location classifier (rule-first)."""

from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# Keep in sync with cv/config/location.json (fallback when file missing).
_DEFAULT_CONFIG = {
    "origin": "Oakland, CA",
    "bayAreaCities": [
        "san francisco",
        "oakland",
        "berkeley",
        "emeryville",
        "south san francisco",
        "daly city",
        "san mateo",
        "foster city",
        "redwood city",
        "menlo park",
        "palo alto",
        "mountain view",
        "sunnyvale",
        "santa clara",
        "san jose",
        "milpitas",
        "fremont",
        "hayward",
        "san leandro",
        "alameda",
        "walnut creek",
        "sf",
        "bay area",
        "san francisco bay area",
        "sf bay area",
        "east bay",
        "south bay",
        "peninsula",
    ],
    "commuteTiers": {
        "preferred": ["Oakland", "Berkeley", "Emeryville", "San Francisco"],
        "acceptable": [
            "San Leandro",
            "Alameda",
            "Walnut Creek",
            "South San Francisco",
            "Daly City",
        ],
        "conditional": [
            "San Mateo",
            "Redwood City",
            "Palo Alto",
            "Mountain View",
            "Sunnyvale",
            "Santa Clara",
            "San Jose",
            "Menlo Park",
            "Foster City",
        ],
    },
    "californiaTokens": [
        "california",
        "ca",
        "pacific time",
        "pt timezone",
        "us - west",
    ],
    "usTokens": [
        "united states",
        "usa",
        "u.s.",
        "us only",
        "nationwide",
        "remote - us",
        "remote us",
    ],
}


def _config_paths() -> list[Path]:
    """Candidate paths for location.json (Docker path is shallow — never IndexError)."""
    paths: list[Path] = []
    env = os.environ.get("LOCATION_CONFIG")
    if env:
        paths.append(Path(env))
    paths.append(Path("/app/config/location.json"))

    here = Path(__file__).resolve()
    # Walk up looking for .../config/location.json (host checkout or image layout)
    for parent in here.parents:
        candidate = parent / "config" / "location.json"
        paths.append(candidate)
        if parent.name == "cv" or (parent / "docker-compose.yml").is_file():
            break

    paths.append(Path.cwd() / "config" / "location.json")

    # Dedupe while preserving order
    seen: set[str] = set()
    out: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


@lru_cache(maxsize=1)
def load_location_config() -> dict:
    for path in _config_paths():
        try:
            if path.is_file():
                with path.open(encoding="utf-8") as fh:
                    data = json.load(fh)
                logger.info("Loaded location config from %s", path)
                return data
        except Exception:
            logger.exception("Failed reading location config %s", path)
    return dict(_DEFAULT_CONFIG)


def reload_location_config() -> dict:
    """Clear the cached config and reload from disk (after editing location.json)."""
    load_location_config.cache_clear()
    return load_location_config()


def _blob(*parts: str | None) -> str:
    return " ".join((p or "") for p in parts).lower()


def assess_location(
    *,
    location: str | None = None,
    title: str | None = None,
    description: str | None = None,
    alert_location: str | None = None,
    work_mode_hint: str | None = None,
) -> dict:
    """Return locationAssessment dict used on cv_jobs."""
    cfg = load_location_config()
    bay_cities = [c.lower() for c in (cfg.get("bayAreaCities") or [])]
    ca_tokens = [c.lower() for c in (cfg.get("californiaTokens") or [])]
    us_tokens = [c.lower() for c in (cfg.get("usTokens") or [])]

    text = _blob(location, title, description, alert_location, work_mode_hint)
    evidence: list[str] = []
    office_cities: list[str] = []

    for city in bay_cities:
        if city and city in text:
            pretty = city.title() if len(city) > 3 else city.upper()
            if pretty not in office_cities:
                office_cities.append(pretty)
            evidence.append(f"mentions {city}")

    # Work arrangement
    work = "unknown"
    if re.search(r"\bremote\b", text) and re.search(r"\bhybrid\b", text):
        work = "hybrid"
        evidence.append("mentions remote and hybrid")
    elif re.search(r"\bhybrid\b", text):
        work = "hybrid"
        evidence.append("mentions hybrid")
    elif re.search(r"\bremote\b", text) or re.search(r"work from home|wfh", text):
        work = "remote"
        evidence.append("mentions remote")
    elif re.search(r"\bonsite\b|\bon-site\b|\bin[- ]office\b", text):
        work = "onsite"
        evidence.append("mentions onsite")
    elif work_mode_hint and work_mode_hint.lower() in ("remote", "hybrid", "onsite"):
        work = work_mode_hint.lower()
        evidence.append(f"workMode hint={work_mode_hint}")

    # Explicit CA exclusions for remote roles
    excludes_ca = bool(
        re.search(
            r"(except|excluding|not\s+in|outside)\s+(of\s+)?california|\bno\s+california\b|california\s+excluded",
            text,
        )
    )
    if excludes_ca:
        evidence.append("excludes California")

    in_bay = bool(office_cities) or bool(
        re.search(r"\bbay area\b|\bsf bay\b|\beast bay\b|\bsouth bay\b", text)
    )
    in_ca = in_bay or any(tok in text for tok in ca_tokens) or bool(
        re.search(r",\s*ca\b|\bca\b", location or "")
    )
    in_us = in_ca or any(tok in text for tok in us_tokens) or bool(
        re.search(r"\bunited states\b|\busa\b|\bu\.s\.\b", text)
    )

    if in_bay:
        geo = "bay_area"
    elif in_ca:
        geo = "california"
    elif in_us:
        geo = "us"
    else:
        geo = "unknown"

    # Eligibility: Bay Area offices / phrases, or any remote (unless CA excluded).
    bay_eligible = False
    if excludes_ca:
        bay_eligible = False
    elif work == "remote":
        bay_eligible = True
        evidence.append("remote always eligible")
        if geo == "unknown":
            geo = "us"
    elif in_bay:
        bay_eligible = True
    elif work in ("hybrid", "onsite") and in_bay:
        bay_eligible = True
    elif alert_location and any(
        c in alert_location.lower() for c in bay_cities[:20]
    ):
        bay_eligible = True
        evidence.append("alert location is Bay Area")
        if geo == "unknown":
            geo = "bay_area"

    confidence = 0.4
    if office_cities:
        confidence += 0.35
    if work != "unknown":
        confidence += 0.15
    if geo != "unknown":
        confidence += 0.1
    if excludes_ca:
        confidence = max(confidence, 0.7)
    confidence = min(1.0, round(confidence, 2))

    return {
        "workArrangement": work,
        "geographicEligibility": geo,
        "officeCities": office_cities[:8],
        "bayAreaEligible": bay_eligible,
        "confidence": confidence,
        "evidence": evidence[:12],
        "commuteTier": _commute_tier(office_cities, cfg),
    }


def _commute_tier(office_cities: list[str], cfg: dict) -> str | None:
    tiers = cfg.get("commuteTiers") or {}
    lowered = {c.lower() for c in office_cities}
    for tier_name in ("preferred", "acceptable", "conditional"):
        cities = tiers.get(tier_name) or []
        for city in cities:
            if city.lower() in lowered or any(city.lower() in oc for oc in lowered):
                return tier_name
    if office_cities:
        return "other"
    return None
