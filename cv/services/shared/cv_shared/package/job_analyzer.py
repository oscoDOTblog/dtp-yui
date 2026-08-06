"""Stage 1: Job Analyzer — structured JD signals for package generation."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..llm import generate
from ..ollama_client import extract_json
from .prompts import JOB_ANALYZER_SYSTEM

logger = logging.getLogger(__name__)

RequirementClass = Literal["critical", "important", "helpful", "unnecessary"]

JOB_ANALYZER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "primaryResponsibilities": {
            "type": "array",
            "items": {"type": "string"},
        },
        "requiredQualifications": {
            "type": "array",
            "items": {"type": "string"},
        },
        "preferredQualifications": {
            "type": "array",
            "items": {"type": "string"},
        },
        "atsKeywords": {"type": "array", "items": {"type": "string"}},
        "culturalSignals": {"type": "array", "items": {"type": "string"}},
        "seniorityExpectations": {"type": "string"},
        "interviewDeciders": {"type": "array", "items": {"type": "string"}},
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "class": {
                        "type": "string",
                        "enum": ["critical", "important", "helpful", "unnecessary"],
                    },
                },
                "required": ["text", "class"],
            },
        },
        "positioning": {"type": "string"},
        "candidateGaps": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "primaryResponsibilities",
        "requiredQualifications",
        "preferredQualifications",
        "atsKeywords",
        "interviewDeciders",
        "requirements",
        "positioning",
        "candidateGaps",
    ],
}


class AnalyzedRequirement(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    text: str
    class_: RequirementClass = Field(alias="class", default="important")

    def to_public(self) -> dict[str, str]:
        return {"text": self.text, "class": self.class_}


class JobAnalysis(BaseModel):
    primaryResponsibilities: list[str] = Field(default_factory=list)
    requiredQualifications: list[str] = Field(default_factory=list)
    preferredQualifications: list[str] = Field(default_factory=list)
    atsKeywords: list[str] = Field(default_factory=list)
    culturalSignals: list[str] = Field(default_factory=list)
    seniorityExpectations: str = ""
    interviewDeciders: list[str] = Field(default_factory=list)
    requirements: list[AnalyzedRequirement] = Field(default_factory=list)
    positioning: str = ""
    candidateGaps: list[str] = Field(default_factory=list)
    source: str = "llm"  # llm | match_fallback
    provider: str | None = None

    def to_public(self) -> dict[str, Any]:
        return {
            "primaryResponsibilities": list(self.primaryResponsibilities),
            "requiredQualifications": list(self.requiredQualifications),
            "preferredQualifications": list(self.preferredQualifications),
            "atsKeywords": list(self.atsKeywords),
            "culturalSignals": list(self.culturalSignals),
            "seniorityExpectations": self.seniorityExpectations,
            "interviewDeciders": list(self.interviewDeciders),
            "requirements": [r.to_public() for r in self.requirements],
            "positioning": self.positioning,
            "candidateGaps": list(self.candidateGaps),
            "source": self.source,
            "provider": self.provider,
        }


def analyze_job_for_package(
    *,
    job: dict,
    match: dict,
    candidate: dict | None = None,
) -> JobAnalysis:
    """LLM job analysis for document generation; falls back to match data."""
    try:
        raw, provider = _call_job_analyzer(job=job, match=match, candidate=candidate)
        analysis = _normalize_analysis(raw, provider=provider, source="llm")
        analysis.atsKeywords = enrich_dual_form_keywords(
            analysis.atsKeywords,
            job_description=str(job.get("descriptionRaw") or ""),
        )
        if analysis.atsKeywords or analysis.requirements or analysis.interviewDeciders:
            return analysis
        logger.warning("Job analyzer returned empty payload; using match fallback")
    except Exception as exc:
        logger.warning("Job analyzer failed, using match fallback: %s", exc)
    return fallback_job_analysis(job=job, match=match)


def fallback_job_analysis(*, job: dict, match: dict) -> JobAnalysis:
    requirements: list[AnalyzedRequirement] = []
    for m in (match.get("strongMatches") or [])[:12]:
        text = str(m.get("requirement") or "").strip()
        if text:
            requirements.append(AnalyzedRequirement.model_validate({"text": text, "class": "important"}))
    for g in (match.get("meaningfulGaps") or [])[:8]:
        text = str(g.get("skill") or g.get("requirement") or "").strip()
        if text:
            requirements.append(AnalyzedRequirement.model_validate({"text": text, "class": "critical"}))

    keywords: list[str] = []
    for m in (match.get("strongMatches") or [])[:15]:
        t = str(m.get("requirement") or "").strip()
        if t and t not in keywords:
            keywords.append(t)
    for skill in (match.get("matchedSkills") or match.get("skills") or [])[:10]:
        if isinstance(skill, str) and skill not in keywords:
            keywords.append(skill)
        elif isinstance(skill, dict):
            name = str(skill.get("name") or skill.get("skill") or "").strip()
            if name and name not in keywords:
                keywords.append(name)

    gaps = [
        str(g.get("skill") or g.get("requirement") or "").strip()
        for g in (match.get("meaningfulGaps") or [])
        if str(g.get("skill") or g.get("requirement") or "").strip()
    ][:8]

    role_family = match.get("roleFamily") or "product"
    positioning = str(job.get("title") or "").strip() or role_family.title()
    jd = str(job.get("descriptionRaw") or "")
    keywords = enrich_dual_form_keywords(keywords[:20], job_description=jd)

    return JobAnalysis(
        primaryResponsibilities=[
            str(m.get("requirement") or "").strip()
            for m in (match.get("strongMatches") or [])[:6]
            if str(m.get("requirement") or "").strip()
        ],
        requiredQualifications=list(keywords[:10]),
        preferredQualifications=[],
        atsKeywords=keywords[:40],
        culturalSignals=[],
        seniorityExpectations=str(match.get("seniority") or match.get("level") or ""),
        interviewDeciders=keywords[:5] or [role_family],
        requirements=requirements,
        positioning=positioning,
        candidateGaps=gaps,
        source="match_fallback",
        provider=None,
    )


def _call_job_analyzer(
    *,
    job: dict,
    match: dict,
    candidate: dict | None,
) -> tuple[dict[str, Any], str]:
    candidate = candidate or {}
    role_family = match.get("roleFamily") or "product"
    prompt = f"""Analyze this job for resume/cover letter tailoring.

Target:
Title: {job.get('title')}
Company: {job.get('company')}
Location: {job.get('location')}
URL: {job.get('url') or '(none)'}

Existing match context (may be incomplete):
Role family: {role_family}
Score: {match.get('score')}/100 ({match.get('recommendation')})
Strong matches: {json.dumps([m.get('requirement') for m in (match.get('strongMatches') or [])[:12]])}
Meaningful gaps: {json.dumps([g.get('skill') for g in (match.get('meaningfulGaps') or [])[:8]])}

Candidate target families (context only): {list((candidate.get('positioningSummaries') or {}).keys())}

Job description:
{(job.get('descriptionRaw') or '')[:6000]}

Return JSON with primaryResponsibilities, requiredQualifications, preferredQualifications,
atsKeywords (exact JD terms; include acronym AND full form when both appear in the JD),
culturalSignals, seniorityExpectations, interviewDeciders (3-5),
requirements (text+class), positioning (headline), candidateGaps.
Do not invent keyword expansions that never appear in the job description.
"""
    result = generate(
        prompt,
        system=JOB_ANALYZER_SYSTEM,
        temperature=0.15,
        process="jobAnalyzer",
        response_format=JOB_ANALYZER_SCHEMA,
    )
    parsed = extract_json(result.text)
    if not isinstance(parsed, dict):
        raise ValueError("job analyzer response was not a JSON object")
    return parsed, result.provider


def _normalize_analysis(
    raw: dict[str, Any],
    *,
    provider: str | None,
    source: str,
) -> JobAnalysis:
    try:
        data = dict(raw)
        # Normalize requirement class key
        reqs = []
        for item in data.get("requirements") or []:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            cls = str(item.get("class") or "important").strip().lower()
            if cls not in ("critical", "important", "helpful", "unnecessary"):
                cls = "important"
            reqs.append({"text": text, "class": cls})
        data["requirements"] = reqs
        analysis = JobAnalysis.model_validate(data)
    except ValidationError:
        analysis = JobAnalysis(
            primaryResponsibilities=_str_list(raw.get("primaryResponsibilities")),
            requiredQualifications=_str_list(raw.get("requiredQualifications")),
            preferredQualifications=_str_list(raw.get("preferredQualifications")),
            atsKeywords=_str_list(raw.get("atsKeywords")),
            culturalSignals=_str_list(raw.get("culturalSignals")),
            seniorityExpectations=str(raw.get("seniorityExpectations") or "").strip(),
            interviewDeciders=_str_list(raw.get("interviewDeciders"))[:5],
            positioning=str(raw.get("positioning") or "").strip(),
            candidateGaps=_str_list(raw.get("candidateGaps")),
        )
        for item in raw.get("requirements") or []:
            if isinstance(item, dict) and item.get("text"):
                cls = str(item.get("class") or "important")
                if cls not in ("critical", "important", "helpful", "unnecessary"):
                    cls = "important"
                analysis.requirements.append(
                    AnalyzedRequirement.model_validate(
                        {"text": str(item["text"]).strip(), "class": cls}
                    )
                )

    analysis.primaryResponsibilities = analysis.primaryResponsibilities[:12]
    analysis.requiredQualifications = analysis.requiredQualifications[:15]
    analysis.preferredQualifications = analysis.preferredQualifications[:12]
    analysis.atsKeywords = analysis.atsKeywords[:40]
    analysis.culturalSignals = analysis.culturalSignals[:10]
    analysis.interviewDeciders = analysis.interviewDeciders[:5]
    analysis.candidateGaps = analysis.candidateGaps[:10]
    analysis.requirements = analysis.requirements[:25]
    analysis.source = source
    analysis.provider = provider
    return analysis


# Known pairs only — both sides must appear in the JD to be dual-listed.
# Never invent a form that is not actually present in the description.
_DUAL_FORM_PAIRS: list[tuple[str, str]] = [
    ("ci/cd", "continuous integration"),
    ("ci/cd", "continuous delivery"),
    ("ci", "continuous integration"),
    ("cd", "continuous delivery"),
    ("aws", "amazon web services"),
    ("k8s", "kubernetes"),
    ("iac", "infrastructure as code"),
    ("sre", "site reliability"),
    ("api", "application programming interface"),
    ("sdk", "software development kit"),
    ("ml", "machine learning"),
    ("ai", "artificial intelligence"),
    ("ui", "user interface"),
    ("ux", "user experience"),
    ("sql", "structured query language"),
]


def enrich_dual_form_keywords(
    keywords: list[str],
    *,
    job_description: str,
    limit: int = 40,
) -> list[str]:
    """Ensure acronym + full form both appear in atsKeywords when JD has both.

    Does not invent expansions missing from the job description.
    """
    jd_lower = (job_description or "").lower()
    out: list[str] = []
    for kw in keywords:
        text = str(kw or "").strip()
        if text and text not in out:
            out.append(text)

    def _has(phrase: str) -> bool:
        p = phrase.lower()
        if len(p) <= 2:
            return bool(re.search(rf"(?<![a-z0-9]){re.escape(p)}(?![a-z0-9])", jd_lower))
        return p in jd_lower

    def _already(phrase: str) -> bool:
        pl = phrase.lower()
        return any(x.lower() == pl for x in out)

    display_map = {
        "ci/cd": "CI/CD",
        "ci": "CI",
        "cd": "CD",
        "aws": "AWS",
        "k8s": "Kubernetes",
        "iac": "IaC",
        "sre": "SRE",
        "api": "API",
        "sdk": "SDK",
        "ml": "ML",
        "ai": "AI",
        "ui": "UI",
        "ux": "UX",
        "sql": "SQL",
        "continuous integration": "continuous integration",
        "continuous delivery": "continuous delivery",
        "amazon web services": "Amazon Web Services",
        "kubernetes": "Kubernetes",
        "infrastructure as code": "infrastructure as code",
        "site reliability": "site reliability",
        "application programming interface": "application programming interface",
        "software development kit": "software development kit",
        "machine learning": "machine learning",
        "artificial intelligence": "artificial intelligence",
        "user interface": "user interface",
        "user experience": "user experience",
        "structured query language": "structured query language",
    }

    for short, full in _DUAL_FORM_PAIRS:
        if _has(short) and _has(full):
            for form in (short, full):
                display = display_map.get(form.lower(), form)
                if not _already(display) and len(out) < limit:
                    out.append(display)
    return out[:limit]


def _str_list(value: Any, limit: int = 40) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out
