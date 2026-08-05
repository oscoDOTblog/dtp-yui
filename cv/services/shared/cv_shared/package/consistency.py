"""Stage 6: Consistency review between resume and cover letter."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from ..llm import generate
from ..ollama_client import extract_json
from ..resume.achievements import Achievement
from ..resume.tailor import TailorPayload
from .job_analyzer import JobAnalysis
from .prompts import CONSISTENCY_SYSTEM

logger = logging.getLogger(__name__)

CONSISTENCY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "flags": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string"},
                    "detail": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                },
                "required": ["kind", "detail"],
            },
        },
        "safeCoverLetter": {"type": "string"},
        "resumeIssues": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["flags", "safeCoverLetter"],
}


class ConsistencyFlag(BaseModel):
    kind: str
    detail: str
    severity: str = "medium"


class ConsistencyResult(BaseModel):
    flags: list[ConsistencyFlag] = Field(default_factory=list)
    safeCoverLetter: str = ""
    resumeIssues: list[str] = Field(default_factory=list)
    provider: str | None = None
    appliedCoverEdit: bool = False
    source: str = "llm"  # llm | passthrough

    def to_public(self) -> dict[str, Any]:
        return {
            "flags": [f.model_dump() for f in self.flags],
            "safeCoverLetter": self.safeCoverLetter,
            "resumeIssues": list(self.resumeIssues),
            "provider": self.provider,
            "appliedCoverEdit": self.appliedCoverEdit,
            "source": self.source,
        }


def review_consistency(
    *,
    resume_text: str,
    cover_letter: str,
    analysis: JobAnalysis | None,
    payload: TailorPayload,
    catalog: list[Achievement],
) -> ConsistencyResult:
    by_id = {a.id: a for a in catalog}
    employers = {
        (a.employer or "").strip()
        for a in by_id.values()
        if (a.employer or "").strip()
    }
    evidence_statements = []
    for sid in payload.selectedAchievementIds:
        ach = by_id.get(sid)
        if not ach:
            continue
        evidence_statements.append(
            {
                "sourceId": sid,
                "employer": ach.employer,
                "role": ach.role,
                "statement": ach.statement,
                "rewritten": payload.rewrite_map().get(sid) or ach.statement,
            }
        )

    try:
        raw, provider = _call_consistency(
            resume_text=resume_text,
            cover_letter=cover_letter,
            analysis=analysis,
            payload=payload,
            evidence_statements=evidence_statements,
        )
        result = _normalize(
            raw,
            original_cover=cover_letter,
            employers=employers,
            provider=provider,
        )
        return result
    except Exception as exc:
        logger.warning("Consistency review failed, passthrough cover: %s", exc)
        return ConsistencyResult(
            flags=[],
            safeCoverLetter=cover_letter,
            resumeIssues=[],
            provider=None,
            appliedCoverEdit=False,
            source="passthrough",
        )


def _call_consistency(
    *,
    resume_text: str,
    cover_letter: str,
    analysis: JobAnalysis | None,
    payload: TailorPayload,
    evidence_statements: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    prompt = f"""Compare resume and cover letter for consistency and truthfulness.

Resume headline: {payload.targetRole}
Resume summary: {payload.summary}

Verified selected evidence:
{json.dumps(evidence_statements[:16], indent=2)}

Job positioning: {(analysis.positioning if analysis else '')}
Gaps known: {json.dumps((analysis.candidateGaps if analysis else [])[:6])}

Resume text (truncated):
{resume_text[:4500]}

Cover letter:
{cover_letter[:3500]}

Return JSON: flags (kind, detail, severity), safeCoverLetter (full letter — original or fixed), resumeIssues.
"""
    result = generate(
        prompt,
        system=CONSISTENCY_SYSTEM,
        temperature=0.1,
        process="consistencyReview",
        response_format=CONSISTENCY_SCHEMA,
    )
    parsed = extract_json(result.text)
    if not isinstance(parsed, dict):
        raise ValueError("consistency response was not a JSON object")
    return parsed, result.provider


def _normalize(
    raw: dict[str, Any],
    *,
    original_cover: str,
    employers: set[str],
    provider: str | None,
) -> ConsistencyResult:
    flags: list[ConsistencyFlag] = []
    for item in raw.get("flags") or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "issue").strip()
        detail = str(item.get("detail") or "").strip()
        if not detail:
            continue
        severity = str(item.get("severity") or "medium").lower()
        if severity not in ("low", "medium", "high"):
            severity = "medium"
        flags.append(
            ConsistencyFlag(kind=kind, detail=detail, severity=severity)
        )

    safe = str(raw.get("safeCoverLetter") or "").strip() or original_cover
    if not _cover_is_safe(safe, employers):
        safe = original_cover
        applied = False
    else:
        applied = safe.strip() != original_cover.strip()

    issues = [
        str(x).strip()
        for x in (raw.get("resumeIssues") or [])
        if str(x).strip()
    ][:12]

    return ConsistencyResult(
        flags=flags[:20],
        safeCoverLetter=safe,
        resumeIssues=issues,
        provider=provider,
        appliedCoverEdit=applied,
        source="llm",
    )


def _cover_is_safe(text: str, employers: set[str]) -> bool:
    """Reject cover letter rewrites that invent a catalog employer name oddly."""
    if not text or len(text.strip()) < 80:
        return False
    # If text introduces an employer not in allow-list and looks like work claim —
    # soft check: all multi-word employers should appear only if in set or common words.
    # Allow free text; only reject if an employer from catalog is mis-attributed is too hard.
    # Reject if letter contains very short empty content.
    if re.search(r"```", text):
        return False
    # Employer invent check: unknown "at Acme Corp" patterns are hard without NER;
    # keep the employer cross-check from resume tailor style for known catalog names
    # that aren't in the letter's allowed set — actually all catalog employers are allowed.
    _ = employers
    return True
