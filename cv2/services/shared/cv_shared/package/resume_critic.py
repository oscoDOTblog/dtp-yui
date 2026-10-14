"""Resume critic stage for multi-stage OpenAI package generation."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from ..llm import generate
from ..ollama_client import extract_json
from .job_analyzer import JobAnalysis
from .prompts import RESUME_CRITIC_SYSTEM

logger = logging.getLogger(__name__)

CRITIC_THRESHOLD_MEAN = 7.0

RESUME_CRITIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "atsCompatibility": {"type": "number"},
        "jobRelevance": {"type": "number"},
        "technicalCredibility": {"type": "number"},
        "clarity": {"type": "number"},
        "seniorityAlignment": {"type": "number"},
        "evidenceQuality": {"type": "number"},
        "recruiterScanability": {"type": "number"},
        "truthfulness": {"type": "number"},
        "mustFix": {"type": "array", "items": {"type": "string"}},
        "optionalImprove": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "atsCompatibility",
        "jobRelevance",
        "technicalCredibility",
        "clarity",
        "seniorityAlignment",
        "evidenceQuality",
        "recruiterScanability",
        "truthfulness",
        "mustFix",
        "optionalImprove",
    ],
}

_SCORE_KEYS = (
    "atsCompatibility",
    "jobRelevance",
    "technicalCredibility",
    "clarity",
    "seniorityAlignment",
    "evidenceQuality",
    "recruiterScanability",
    "truthfulness",
)


class ResumeCriticResult(BaseModel):
    atsCompatibility: float = 7
    jobRelevance: float = 7
    technicalCredibility: float = 7
    clarity: float = 7
    seniorityAlignment: float = 7
    evidenceQuality: float = 7
    recruiterScanability: float = 7
    truthfulness: float = 7
    mustFix: list[str] = Field(default_factory=list)
    optionalImprove: list[str] = Field(default_factory=list)
    provider: str | None = None
    source: str = "llm"

    @property
    def mean(self) -> float:
        vals = [getattr(self, k) for k in _SCORE_KEYS]
        return sum(vals) / len(vals) if vals else 0.0

    def needs_revision(self) -> bool:
        return bool(self.mustFix) or self.mean < CRITIC_THRESHOLD_MEAN

    def feedback_text(self) -> str:
        parts = []
        if self.mustFix:
            parts.append("Must fix:\n" + "\n".join(f"- {x}" for x in self.mustFix))
        if self.optionalImprove:
            parts.append(
                "Optional improvements:\n"
                + "\n".join(f"- {x}" for x in self.optionalImprove[:6])
            )
        parts.append(f"Mean score: {self.mean:.1f}/10")
        return "\n\n".join(parts)

    def to_public(self) -> dict[str, Any]:
        data = {k: getattr(self, k) for k in _SCORE_KEYS}
        data["mustFix"] = list(self.mustFix)
        data["optionalImprove"] = list(self.optionalImprove)
        data["mean"] = round(self.mean, 2)
        data["provider"] = self.provider
        data["source"] = self.source
        data["needsRevision"] = self.needs_revision()
        return data


def critique_resume(
    *,
    resume_preview: str,
    job: dict,
    analysis: JobAnalysis,
    payload_report: dict[str, Any],
) -> ResumeCriticResult:
    try:
        raw, provider = _call_critic(
            resume_preview=resume_preview,
            job=job,
            analysis=analysis,
            payload_report=payload_report,
        )
        return _normalize(raw, provider=provider)
    except Exception as exc:
        logger.warning("Resume critic failed, skip revision: %s", exc)
        return ResumeCriticResult(
            mustFix=[],
            optionalImprove=[],
            provider=None,
            source="skipped",
            atsCompatibility=8,
            jobRelevance=8,
            technicalCredibility=8,
            clarity=8,
            seniorityAlignment=8,
            evidenceQuality=8,
            recruiterScanability=8,
            truthfulness=8,
        )


def _call_critic(
    *,
    resume_preview: str,
    job: dict,
    analysis: JobAnalysis,
    payload_report: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    prompt = f"""Critique this tailored resume for the target role.

Job: {job.get('title')} @ {job.get('company')}
Positioning goal: {analysis.positioning}
Interview deciders: {json.dumps(analysis.interviewDeciders)}
ATS keywords: {json.dumps(analysis.atsKeywords[:20])}
Known gaps: {json.dumps(analysis.candidateGaps[:6])}

Tailor selection report:
{json.dumps(payload_report, indent=2)[:3000]}

Resume text:
{resume_preview[:5000]}

Score 1–10 dimensions and list mustFix / optionalImprove.
"""
    result = generate(
        prompt,
        system=RESUME_CRITIC_SYSTEM,
        temperature=0.15,
        process="resumeCritic",
        response_format=RESUME_CRITIC_SCHEMA,
    )
    parsed = extract_json(result.text)
    if not isinstance(parsed, dict):
        raise ValueError("critic response was not a JSON object")
    return parsed, result.provider


def _normalize(raw: dict[str, Any], *, provider: str | None) -> ResumeCriticResult:
    scores: dict[str, float] = {}
    for key in _SCORE_KEYS:
        try:
            val = float(raw.get(key) or 7)
        except (TypeError, ValueError):
            val = 7.0
        scores[key] = max(1.0, min(10.0, val))

    must_fix = [
        str(x).strip() for x in (raw.get("mustFix") or []) if str(x).strip()
    ][:10]
    optional = [
        str(x).strip() for x in (raw.get("optionalImprove") or []) if str(x).strip()
    ][:10]

    try:
        return ResumeCriticResult(
            **scores,
            mustFix=must_fix,
            optionalImprove=optional,
            provider=provider,
            source="llm",
        )
    except ValidationError:
        return ResumeCriticResult(
            mustFix=must_fix,
            optionalImprove=optional,
            provider=provider,
            source="llm",
        )
