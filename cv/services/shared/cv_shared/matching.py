"""Job requirement extraction and evidence-grounded matching."""

from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from . import collections as C
from .db import get_db
from .ollama_client import chat, extract_json

logger = logging.getLogger(__name__)

EXTRACT_SYSTEM = """You extract structured job requirements as JSON only.
Return exactly one JSON object with keys:
title, company, location, workMode, salaryMin, salaryMax, currency,
requiredSkills (string array), preferredSkills (string array),
seniority, roleFamily (one of: systems, product, mobile, ai, other),
hardDisqualifiers (string array), summary (short string).
Do not invent salary if absent — use null. workMode is remote|hybrid|onsite|unknown.
"""

ROLE_FAMILY_KEYWORDS = {
    "systems": [
        "systems engineer",
        "platform",
        "infrastructure",
        "devops",
        "sre",
        "data streaming",
        "spark",
        "terraform",
        "observability",
        "kubernetes",
        "linux",
    ],
    "mobile": ["ios", "android", "swift", "kotlin", "mobile engineer", "react native"],
    "ai": ["ai engineer", "ml engineer", "llm", "machine learning", "genai"],
    "product": [
        "full-stack",
        "fullstack",
        "frontend",
        "product engineer",
        "forward deployed",
        "react",
        "next.js",
    ],
}

ADJACENT = {
    "kubernetes": ["docker", "docker compose", "serverless framework", "ecs"],
    "terraform": ["cloudformation", "serverless framework", "chef"],
    "golang": ["python", "javascript"],
    "go": ["python", "javascript"],
    "rust": ["python", "c++"],
    "kafka": ["apache spark", "sns", "async job processing"],
    "postgres": ["sql", "dynamodb", "mongodb", "snowflake"],
    "postgresql": ["sql", "dynamodb", "mongodb", "snowflake"],
}


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def slugify(text: str) -> str:
    text = (text or "item").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:60] or "item"


def detect_role_family(title: str, description: str, extracted: dict | None = None) -> str:
    if extracted and extracted.get("roleFamily") in ROLE_FAMILY_KEYWORDS:
        return extracted["roleFamily"]
    blob = f"{title} {description}".lower()
    scores = {
        family: sum(1 for kw in kws if kw in blob)
        for family, kws in ROLE_FAMILY_KEYWORDS.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "product"


def _normalize_skill(name: str) -> str:
    return re.sub(r"[^a-z0-9+#.]+", " ", (name or "").lower()).strip()


def _skill_lookup(skills: list[dict]) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for skill in skills:
        keys = [skill["name"], *(skill.get("aliases") or [])]
        for key in keys:
            lookup[_normalize_skill(key)] = skill
    return lookup


def _find_skill(req: str, lookup: dict[str, dict]) -> dict | None:
    norm = _normalize_skill(req)
    if norm in lookup:
        return lookup[norm]
    for key, skill in lookup.items():
        if key and (key in norm or norm in key):
            return skill
    return None


def _adjacent_for(req: str, lookup: dict[str, dict]) -> list[str]:
    norm = _normalize_skill(req)
    found = []
    for key, adj_list in ADJACENT.items():
        if key in norm or norm in key:
            for adj in adj_list:
                if _find_skill(adj, lookup):
                    found.append(adj)
    return found


_PLACEHOLDER_TITLES = frozenset(
    {"", "untitled", "untitled role", "unknown", "n/a", "na", "none", "null"}
)
_PLACEHOLDER_COMPANIES = frozenset(
    {"", "unknown", "n/a", "na", "none", "null", "untitled"}
)


def is_placeholder_title(value: str | None) -> bool:
    return (value or "").strip().lower() in _PLACEHOLDER_TITLES


def is_placeholder_company(value: str | None) -> bool:
    return (value or "").strip().lower() in _PLACEHOLDER_COMPANIES


def clean_title_hint(value: str | None) -> str:
    text = (value or "").strip()
    return "" if is_placeholder_title(text) else text


def clean_company_hint(value: str | None) -> str:
    text = (value or "").strip()
    return "" if is_placeholder_company(text) else text


def seed_placeholders_from_description(raw: dict[str, Any]) -> dict[str, Any]:
    """Fill Untitled/Unknown/empty location/workMode from description text before gates."""
    out = dict(raw or {})
    desc = (out.get("descriptionText") or out.get("descriptionRaw") or "").strip()
    if not desc:
        return out
    if is_placeholder_title(out.get("title")):
        guessed = _guess_title_from_description(desc)
        if guessed:
            out["title"] = guessed
    if is_placeholder_company(out.get("company")):
        guessed = _guess_company_from_description(desc)
        if guessed:
            out["company"] = guessed
    if not (out.get("location") or "").strip():
        guessed = _guess_location(desc)
        if guessed:
            out["location"] = guessed
    mode = (out.get("workMode") or "").strip().lower()
    if mode in ("", "unknown"):
        guessed = _guess_work_mode(desc)
        if guessed != "unknown":
            out["workMode"] = guessed
    return out


def _guess_title_from_description(description: str) -> str:
    """Best-effort role title from pasted/fetched listing text."""
    for raw in (description or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or len(line) < 4 or len(line) > 120:
            continue
        if re.match(r"^https?://", line, flags=re.I):
            continue
        lower = line.lower()
        if lower.startswith(
            (
                "job description",
                "about the role",
                "about this role",
                "about the job",
                "responsibilities",
                "requirements",
                "what you'll",
                "what you will",
                "who we are",
                "overview",
            )
        ):
            continue
        labeled = re.match(
            r"^(?:job\s+)?(?:title|role|position)\s*[:\-–—]\s*(.+)$",
            line,
            flags=re.I,
        )
        if labeled:
            return labeled.group(1).strip()[:120]
        # "Senior Engineer — Netflix" / "Role at Company"
        parts = re.split(r"\s+[|\-–—]\s+|\s+at\s+", line, maxsplit=1, flags=re.I)
        candidate = parts[0].strip()
        if len(candidate) >= 4:
            return candidate[:120]
    return ""


def _guess_company_from_description(description: str) -> str:
    for raw in (description or "").splitlines()[:12]:
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or len(line) > 80:
            continue
        labeled = re.match(
            r"^(?:company|employer|organization)\s*[:\-–—]\s*(.+)$",
            line,
            flags=re.I,
        )
        if labeled:
            return labeled.group(1).strip()[:80]
        at_match = re.search(r"\bat\s+([A-Z][\w.&'’\- ]{1,60})$", line)
        if at_match and not is_placeholder_company(at_match.group(1)):
            return at_match.group(1).strip()[:80]
    return ""


def _guess_work_mode(description: str) -> str:
    blob = (description or "").lower()
    if re.search(r"\b(fully\s+)?remote\b", blob) and "not remote" not in blob:
        if re.search(r"\bhybrid\b", blob):
            return "hybrid"
        return "remote"
    if re.search(r"\bhybrid\b", blob):
        return "hybrid"
    if re.search(r"\b(on[-\s]?site|in[-\s]?office)\b", blob):
        return "onsite"
    return "unknown"


def _guess_location(description: str) -> str:
    for raw in (description or "").splitlines()[:20]:
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or len(line) > 100:
            continue
        labeled = re.match(
            r"^(?:location|based in|office)\s*[:\-–—]\s*(.+)$",
            line,
            flags=re.I,
        )
        if labeled:
            return labeled.group(1).strip()[:120]
        if re.search(
            r"\b(san francisco|bay area|oakland|berkeley|palo alto|"
            r"mountain view|sunnyvale|san jose|remote)\b",
            line,
            flags=re.I,
        ):
            return line[:120]
    return ""


def extract_job_requirements(description: str, title: str = "", company: str = "") -> dict:
    hint_title = clean_title_hint(title)
    hint_company = clean_company_hint(company)
    prompt = (
        f"Title hint: {hint_title or '(unknown — extract from description)'}\n"
        f"Company hint: {hint_company or '(unknown — extract from description)'}\n\n"
        f"Job description:\n{description[:12000]}"
    )
    heuristic = _heuristic_extract(description, hint_title, hint_company)
    try:
        raw = chat(
            prompt,
            system=EXTRACT_SYSTEM,
            temperature=0.1,
            think_process="jobExtract",
        )
        data = extract_json(raw)
        if not isinstance(data, dict):
            raise ValueError("expected object")
    except Exception as exc:
        logger.warning("Ollama extract failed, using heuristic: %s", exc)
        return heuristic

    # Never keep placeholder leftovers when the heuristic found something better
    if is_placeholder_title(data.get("title")):
        data["title"] = heuristic.get("title") or data.get("title")
    if is_placeholder_company(data.get("company")):
        data["company"] = heuristic.get("company") or data.get("company")
    if not (data.get("location") or "").strip():
        data["location"] = heuristic.get("location") or ""
    work_mode = (data.get("workMode") or "").strip().lower()
    if work_mode in ("", "unknown"):
        data["workMode"] = heuristic.get("workMode") or "unknown"
    if not data.get("requiredSkills"):
        data["requiredSkills"] = heuristic.get("requiredSkills") or []
    if not data.get("roleFamily"):
        data["roleFamily"] = heuristic.get("roleFamily")
    return data


def _heuristic_extract(description: str, title: str, company: str) -> dict:
    lines = [ln.strip() for ln in description.splitlines() if ln.strip()]
    skills = []
    skill_hints = [
        "python",
        "javascript",
        "typescript",
        "react",
        "next.js",
        "aws",
        "lambda",
        "terraform",
        "docker",
        "kubernetes",
        "spark",
        "kafka",
        "swift",
        "kotlin",
        "fastapi",
        "java",
        "linux",
        "splunk",
        "datadog",
        "jenkins",
        "snowflake",
    ]
    blob = description.lower()
    for hint in skill_hints:
        if hint in blob:
            skills.append(hint.title() if hint != "next.js" else "Next.js")
    resolved_title = (
        clean_title_hint(title)
        or _guess_title_from_description(description)
        or (lines[0][:120] if lines else "")
    )
    resolved_company = clean_company_hint(company) or _guess_company_from_description(
        description
    )
    return {
        "title": resolved_title or "Untitled role",
        "company": resolved_company or "Unknown",
        "location": _guess_location(description),
        "workMode": _guess_work_mode(description),
        "salaryMin": None,
        "salaryMax": None,
        "currency": "USD",
        "requiredSkills": skills[:12],
        "preferredSkills": [],
        "seniority": "unknown",
        "roleFamily": detect_role_family(resolved_title, description),
        "hardDisqualifiers": [],
        "summary": (description[:400] + "…") if len(description) > 400 else description,
    }


def score_job(job: dict, extracted: dict | None = None) -> dict:
    db = get_db()
    candidate = db[C.CANDIDATES].find_one({"_id": "primary-candidate"}) or {}
    skills = list(db[C.SKILLS].find({"candidateId": "primary-candidate"}))
    evidence = list(db[C.EVIDENCE].find({"candidateId": "primary-candidate", "approvedForResume": True}))
    lookup = _skill_lookup(skills)
    evidence_by_skill: dict[str, list[dict]] = {}
    for ev in evidence:
        for sid in ev.get("skillIds") or []:
            evidence_by_skill.setdefault(sid, []).append(ev)

    extracted = extracted or {}
    title = extracted.get("title") or job.get("title") or ""
    description = job.get("descriptionRaw") or ""
    role_family = detect_role_family(title, description, extracted)

    required = list(extracted.get("requiredSkills") or [])
    preferred = list(extracted.get("preferredSkills") or [])
    all_reqs = required + [p for p in preferred if p not in required]

    strong_matches = []
    warnings = []
    meaningful_gaps = []
    adjacent_hits = []
    verified = 0
    adjacent_score = 0
    checked = 0

    major_gap_tokens = (
        "kafka",
        "kubernetes",
        "k8s",
        "perforce",
        "p4",
        "puppet",
        "clearance",
        "citizenship",
        "on-prem",
        "on prem",
        "on-call",
    )

    for req in all_reqs:
        checked += 1
        skill = _find_skill(req, lookup)
        is_required = req in required
        req_l = req.lower()
        is_major = any(tok in req_l for tok in major_gap_tokens)

        if skill and skill.get("approvedForResume"):
            evs = evidence_by_skill.get(skill["_id"], [])
            level = skill.get("evidenceLevel") or "implemented"
            # Lower evidence levels are strengths but still yellow-leaning warnings
            if level in ("mentioned", "installed"):
                warnings.append(
                    {
                        "skill": req,
                        "severity": "warning",
                        "fit": "warning",
                        "label": "Limited evidence",
                        "reason": f"Present in your bank at evidence level “{level}” — strengthen before claiming expertise.",
                        "adjacentSkills": [],
                        "skillIds": [skill["_id"]],
                        "evidenceIds": [e["_id"] for e in evs[:3]],
                        "evidenceLevel": level,
                    }
                )
            else:
                strong_matches.append(
                    {
                        "requirement": req,
                        "fit": "strong",
                        "label": "Strong",
                        "skillIds": [skill["_id"]],
                        "evidenceIds": [e["_id"] for e in evs[:3]],
                        "evidenceLevel": level,
                    }
                )
                verified += 1
            continue

        adj = _adjacent_for(req, lookup)
        if adj:
            adjacent_hits.append({"requirement": req, "adjacentSkills": adj})
            adjacent_score += 1
            warnings.append(
                {
                    "skill": req,
                    "severity": "warning",
                    "fit": "warning",
                    "label": "Adjacent / moderate",
                    "reason": (
                        f"{'Required' if is_required else 'Preferred'}; no direct evidence. "
                        f"Adjacent strengths: {', '.join(adj)}."
                    ),
                    "adjacentSkills": adj,
                }
            )
            continue

        if is_required or is_major:
            meaningful_gaps.append(
                {
                    "skill": req,
                    "severity": "critical" if is_major or req_l in ("security clearance", "us citizenship") else "high",
                    "fit": "gap",
                    "label": "Major gap" if is_major else "Gap",
                    "reason": (
                        "Central/required for this role, but no direct repository or CV evidence was found."
                        if is_required
                        else "No direct evidence found for this listed qualification."
                    ),
                    "adjacentSkills": [],
                }
            )
        else:
            warnings.append(
                {
                    "skill": req,
                    "severity": "warning",
                    "fit": "warning",
                    "label": "Preferred gap",
                    "reason": "Listed as preferred; missing from your approved evidence bank.",
                    "adjacentSkills": [],
                }
            )

    # Component scores 0–100
    verified_pct = (verified / checked * 100) if checked else 50
    adjacent_pct = min(100, (adjacent_score / max(checked, 1) * 100) + (verified_pct * 0.3))

    preferred_roles = [r.lower() for r in (candidate.get("preferredRoles") or [])]
    role_align = 40
    title_l = title.lower()
    for pr in preferred_roles:
        if any(tok in title_l for tok in pr.lower().split() if len(tok) > 3):
            role_align = 90
            break
    if role_family in ("systems", "product", "mobile", "ai"):
        role_align = max(role_align, 70)

    # Location / comp / work mode
    loc_score = 70
    pref_locs = [x.lower() for x in (candidate.get("preferredLocations") or [])]
    loc = (extracted.get("location") or job.get("location") or "").lower()
    work_mode = (extracted.get("workMode") or job.get("workMode") or "unknown").lower()
    if work_mode == "remote" or any(p in loc for p in pref_locs if p):
        loc_score = 95
    elif work_mode == "hybrid" and ("bay" in loc or "oakland" in loc or "francisco" in loc):
        loc_score = 90

    salary_min = extracted.get("salaryMin") or (job.get("salary") or {}).get("minimum")
    min_wanted = candidate.get("minimumSalary") or 120000
    if salary_min is None:
        comp_part = 70
    elif salary_min >= min_wanted:
        comp_part = 95
    elif salary_min >= min_wanted * 0.85:
        comp_part = 60
    else:
        comp_part = 25
    fit_score = (loc_score + comp_part) / 2

    seniority = (extracted.get("seniority") or "").lower()
    seniority_score = 75
    if "staff" in seniority or "principal" in seniority or "staff" in title_l:
        seniority_score = 70  # stretch but viable given Principal Associate
    if "junior" in seniority or "intern" in seniority:
        seniority_score = 40

    interest = 80 if role_family in ("systems", "product", "mobile", "ai") else 55

    hard = list(extracted.get("hardDisqualifiers") or [])
    hard_penalty = 0
    for h in hard:
        hl = h.lower()
        if "clearance" in hl or "citizen" in hl:
            hard_penalty += 40
            meaningful_gaps.append(
                {
                    "skill": h,
                    "severity": "critical",
                    "fit": "gap",
                    "label": "Hard disqualifier",
                    "reason": "Hard eligibility requirement that may disqualify.",
                    "adjacentSkills": [],
                }
            )

    # Years-of-experience stretch (e.g. 12+ years) — warning, not inventable
    years_match = re.search(r"(\d+)\s*\+?\s*years?", description.lower())
    if years_match and int(years_match.group(1)) >= 10:
        warnings.append(
            {
                "skill": f"{years_match.group(1)}+ years experience",
                "severity": "warning",
                "fit": "warning",
                "label": "Seniority stretch",
                "reason": (
                    f"Posting asks for ~{years_match.group(1)}+ years. "
                    "Capital One (2018–2024) plus independent work may not fully meet a literal 12+ mission-critical infra bar."
                ),
                "adjacentSkills": [],
            }
        )

    if "staff" in title_l or "staff" in seniority:
        warnings.append(
            {
                "skill": "Staff-level scope",
                "severity": "warning",
                "fit": "warning",
                "label": "Level stretch",
                "reason": "Staff title implies deep ownership of mission-critical systems; position carefully if evidence is adjacent rather than exact.",
                "adjacentSkills": [],
            }
        )

    final = (
        0.25 * role_align
        + 0.25 * verified_pct
        + 0.15 * min(100, adjacent_pct)
        + 0.15 * fit_score
        + 0.10 * seniority_score
        + 0.10 * interest
        - hard_penalty
    )
    final = int(max(0, min(100, round(final))))

    urgent = int(os.environ.get("SCORE_URGENT", "85"))
    digest = int(os.environ.get("SCORE_DIGEST", "70"))
    if hard_penalty >= 40:
        recommendation = "reject"
    elif final >= urgent:
        recommendation = "apply"
    elif final >= digest:
        recommendation = "consider"
    else:
        recommendation = "skip"

    why_viable = None
    if (meaningful_gaps or warnings) and final >= digest:
        why_viable = (
            "Gaps are secondary to stronger verified evidence in the posting's core themes."
            if strong_matches
            else "Adjacent experience may cover some gaps; review carefully before applying."
        )

    profile_version = int(
        os.environ.get("PROFILE_VERSION")
        or candidate.get("profileVersion")
        or 1
    )

    return {
        "_id": f"match_{job['_id']}",
        "candidateId": "primary-candidate",
        "jobId": job["_id"],
        "score": final,
        "recommendation": recommendation,
        "roleFamily": role_family,
        "components": {
            "roleAlignment": round(role_align, 1),
            "verifiedEvidence": round(verified_pct, 1),
            "adjacentExperience": round(min(100, adjacent_pct), 1),
            "locationCompFit": round(fit_score, 1),
            "seniorityFit": round(seniority_score, 1),
            "personalInterest": round(interest, 1),
            "hardPenalty": hard_penalty,
        },
        "strongMatches": strong_matches[:20],
        "warnings": warnings[:15],
        "meaningfulGaps": meaningful_gaps[:15],
        "adjacentHits": adjacent_hits[:10],
        "whyViable": why_viable,
        "extracted": extracted,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "profileVersion": profile_version,
    }


def analyze_job(job_id: str) -> dict:
    db = get_db()
    job = db[C.JOBS].find_one({"_id": job_id})
    if not job:
        raise KeyError(f"job not found: {job_id}")

    extracted = extract_job_requirements(
        job.get("descriptionRaw") or "",
        title=job.get("title") or "",
        company=job.get("company") or "",
    )

    # Enrich job fields from extraction when missing / still placeholder
    updates: dict[str, Any] = {
        "requiredSkills": extracted.get("requiredSkills") or [],
        "preferredSkills": extracted.get("preferredSkills") or [],
        "status": "analyzed",
        "roleFamily": detect_role_family(
            clean_title_hint(extracted.get("title"))
            or clean_title_hint(job.get("title"))
            or "",
            job.get("descriptionRaw") or "",
            extracted,
        ),
    }
    extracted_title = clean_title_hint(extracted.get("title"))
    if extracted_title and is_placeholder_title(job.get("title")):
        updates["title"] = extracted_title
    extracted_company = clean_company_hint(extracted.get("company"))
    if extracted_company and is_placeholder_company(job.get("company")):
        updates["company"] = extracted_company
    if (extracted.get("location") or "").strip():
        updates["location"] = extracted["location"].strip()
    extracted_mode = (extracted.get("workMode") or "").strip().lower()
    if extracted_mode and extracted_mode != "unknown":
        updates["workMode"] = extracted_mode
    if extracted.get("salaryMin") or extracted.get("salaryMax"):
        updates["salary"] = {
            "minimum": extracted.get("salaryMin"),
            "maximum": extracted.get("salaryMax"),
            "currency": extracted.get("currency") or "USD",
        }
    db[C.JOBS].update_one({"_id": job_id}, {"$set": updates})
    job = db[C.JOBS].find_one({"_id": job_id})

    match = score_job(job, extracted)
    db[C.JOB_MATCHES].replace_one({"_id": match["_id"]}, match, upsert=True)

    try:
        from .gap_insights import record_gaps_from_match

        record_gaps_from_match(match, job)
    except Exception:
        logger.exception("gap insights upsert failed for job %s", job_id)

    db[C.SYSTEM_RUNS].insert_one(
        {
            "type": "analyze",
            "jobId": job_id,
            "score": match["score"],
            "startedAt": match["generatedAt"],
            "finishedAt": match["generatedAt"],
        }
    )
    return match
