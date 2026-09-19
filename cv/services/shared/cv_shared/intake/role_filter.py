"""SWE / SWE-adjacent title gate (rule-first, config-driven)."""

from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# Keep in sync with cv/config/roleFilter.json (fallback when file missing).
_DEFAULT_CONFIG = {
    "includeTitlePatterns": [
        "software engineer",
        "software developer",
        "swe",
        "full-stack",
        "full stack",
        "fullstack",
        "frontend",
        "backend",
        "platform engineer",
        "systems engineer",
        "devops",
        "sre",
        "site reliability",
        "infrastructure engineer",
        "cloud engineer",
        "security engineer",
        "mobile engineer",
        "ios engineer",
        "android engineer",
        "ml engineer",
        "machine learning engineer",
        "ai engineer",
        "data engineer",
        "staff engineer",
        "principal engineer",
        "founding engineer",
        "solutions engineer",
        "forward deployed",
        "product engineer",
        "developer",
        "programmer",
    ],
    "excludeTitlePatterns": [
        "recruiter",
        "talent acquisition",
        "account executive",
        "customer success",
        "marketing manager",
        "product manager",
        "product owner",
        "program manager",
        "project manager",
        "sales director",
        "sales manager",
        "nurse",
        "attorney",
        "accountant",
        "human resources",
        "graphic designer",
        "ux designer",
        "ui designer",
        "product designer",
    ],
    "includeDescriptionPatterns": [
        "software engineer",
        "software developer",
        "full-stack",
        "full stack",
        "backend engineer",
        "frontend engineer",
        "platform engineer",
    ],
    "ambiguousTitleTokens": ["engineer", "developer", "programmer"],
}


def _config_paths() -> list[Path]:
    paths: list[Path] = []
    env = os.environ.get("ROLE_FILTER_CONFIG")
    if env:
        paths.append(Path(env))
    paths.append(Path("/app/config/roleFilter.json"))

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "roleFilter.json"
        paths.append(candidate)
        if parent.name == "cv" or (parent / "docker-compose.yml").is_file():
            break

    paths.append(Path.cwd() / "config" / "roleFilter.json")

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
def load_role_filter_config() -> dict:
    for path in _config_paths():
        try:
            if path.is_file():
                with path.open(encoding="utf-8") as fh:
                    data = json.load(fh)
                logger.info("Loaded role filter config from %s", path)
                return data
        except Exception:
            logger.exception("Failed reading role filter config %s", path)
    return dict(_DEFAULT_CONFIG)


def reload_role_filter_config() -> dict:
    """Clear the cached config and reload from disk."""
    load_role_filter_config.cache_clear()
    return load_role_filter_config()


def _matches_any(text: str, patterns: list[str]) -> list[str]:
    hits: list[str] = []
    for pattern in patterns:
        p = (pattern or "").strip().lower()
        if p and p in text:
            hits.append(p)
    return hits


def _title_is_ambiguous(title: str, ambiguous_tokens: list[str]) -> bool:
    """True when title is essentially just 'engineer' / 'developer' (+ seniority noise)."""
    cleaned = re.sub(r"[^a-z0-9\s]", " ", (title or "").lower())
    tokens = [t for t in cleaned.split() if t]
    noise = {
        "senior",
        "sr",
        "junior",
        "jr",
        "staff",
        "principal",
        "lead",
        "i",
        "ii",
        "iii",
        "iv",
        "v",
        "1",
        "2",
        "3",
        "4",
        "5",
        "remote",
        "hybrid",
        "onsite",
        "the",
        "a",
        "an",
    }
    core = [t for t in tokens if t not in noise]
    if not core:
        return False
    ambiguous = {t.lower() for t in ambiguous_tokens if t}
    return all(t in ambiguous for t in core) and any(t in ambiguous for t in core)


def assess_role_fit(
    *,
    title: str | None = None,
    description: str | None = None,
) -> dict:
    """Return roleAssessment used on cv_jobs."""
    cfg = load_role_filter_config()
    includes = [p.lower() for p in (cfg.get("includeTitlePatterns") or [])]
    excludes = [p.lower() for p in (cfg.get("excludeTitlePatterns") or [])]
    desc_includes = [p.lower() for p in (cfg.get("includeDescriptionPatterns") or [])]
    ambiguous_tokens = [
        t.lower() for t in (cfg.get("ambiguousTitleTokens") or ["engineer", "developer"])
    ]

    title_l = (title or "").lower().strip()
    # Cap description scan for speed
    desc_l = ((description or "")[:4000]).lower()

    evidence: list[str] = []
    matched_excludes = _matches_any(title_l, excludes)
    if matched_excludes:
        evidence.append(f"title excluded by {matched_excludes[0]}")
        return {
            "roleEligible": False,
            "matchedIncludes": [],
            "matchedExcludes": matched_excludes[:8],
            "confidence": 0.95,
            "evidence": evidence[:12],
        }

    matched_includes = _matches_any(title_l, includes)
    if matched_includes:
        evidence.append(f"title matches {matched_includes[0]}")
        return {
            "roleEligible": True,
            "matchedIncludes": matched_includes[:8],
            "matchedExcludes": [],
            "confidence": 0.9,
            "evidence": evidence[:12],
        }

    # Ambiguous short titles: allow description boost
    if _title_is_ambiguous(title_l, ambiguous_tokens):
        desc_hits = _matches_any(desc_l, desc_includes or includes)
        if desc_hits:
            evidence.append("ambiguous title; description matches SWE pattern")
            evidence.append(f"description matches {desc_hits[0]}")
            return {
                "roleEligible": True,
                "matchedIncludes": desc_hits[:8],
                "matchedExcludes": [],
                "confidence": 0.55,
                "evidence": evidence[:12],
            }
        evidence.append("ambiguous eng title without SWE description signal")
    else:
        evidence.append("no SWE/SWE-adjacent title match")

    return {
        "roleEligible": False,
        "matchedIncludes": [],
        "matchedExcludes": [],
        "confidence": 0.7,
        "evidence": evidence[:12],
    }
