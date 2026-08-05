"""Stage 2–3: Evidence Ranker — score catalog items for the target role."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from ..llm import generate
from ..ollama_client import extract_json
from ..resume.achievements import Achievement
from ..resume.tailor import PROJECT_PRIORITY
from .job_analyzer import JobAnalysis
from .prompts import EVIDENCE_RANKER_SYSTEM

logger = logging.getLogger(__name__)

EVIDENCE_RANKER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "achievements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sourceId": {"type": "string"},
                    "score": {"type": "number"},
                    "reasons": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["sourceId", "score"],
            },
        },
        "skillIds": {"type": "array", "items": {"type": "string"}},
        "projectIds": {"type": "array", "items": {"type": "string"}},
        "recommendedBulletCap": {"type": "integer"},
        "highlightSourceIds": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "achievements",
        "skillIds",
        "projectIds",
        "highlightSourceIds",
    ],
}


class RankedAchievement(BaseModel):
    sourceId: str
    score: float = 0
    reasons: list[str] = Field(default_factory=list)


class EvidenceRanking(BaseModel):
    achievements: list[RankedAchievement] = Field(default_factory=list)
    skillIds: list[str] = Field(default_factory=list)
    projectIds: list[str] = Field(default_factory=list)
    recommendedBulletCap: int | None = None
    highlightSourceIds: list[str] = Field(default_factory=list)
    source: str = "llm"  # llm | deterministic
    provider: str | None = None

    def score_map(self) -> dict[str, float]:
        return {a.sourceId: a.score for a in self.achievements}

    def ordered_ids(self, limit: int | None = None) -> list[str]:
        ordered = sorted(
            self.achievements, key=lambda a: a.score, reverse=True
        )
        ids = [a.sourceId for a in ordered]
        if limit is not None:
            return ids[:limit]
        return ids

    def to_public(self) -> dict[str, Any]:
        return {
            "achievements": [
                {
                    "sourceId": a.sourceId,
                    "score": a.score,
                    "reasons": list(a.reasons),
                }
                for a in self.achievements
            ],
            "skillIds": list(self.skillIds),
            "projectIds": list(self.projectIds),
            "recommendedBulletCap": self.recommendedBulletCap,
            "highlightSourceIds": list(self.highlightSourceIds),
            "source": self.source,
            "provider": self.provider,
        }


def rank_evidence(
    *,
    analysis: JobAnalysis,
    match: dict,
    catalog: list[Achievement],
    skills: list[dict],
    projects: list[dict],
    max_bullets: int,
) -> EvidenceRanking:
    approved = [a for a in catalog if a.approvedForResume]
    by_id = {a.id: a for a in approved}
    approved_skill_ids = {
        s["_id"] for s in skills if s.get("approvedForResume") and s.get("_id")
    }
    try:
        raw, provider = _call_ranker(
            analysis=analysis,
            match=match,
            catalog=approved,
            skills=skills,
            max_bullets=max_bullets,
        )
        ranking = _normalize_ranking(
            raw,
            by_id=by_id,
            approved_skill_ids=approved_skill_ids,
            max_bullets=max_bullets,
            provider=provider,
            source="llm",
        )
        if ranking.achievements:
            return ranking
        logger.warning("Evidence ranker returned empty; using deterministic fallback")
    except Exception as exc:
        logger.warning("Evidence ranker failed, deterministic fallback: %s", exc)
    return deterministic_rank(
        analysis=analysis,
        match=match,
        catalog=approved,
        skills=skills,
        max_bullets=max_bullets,
    )


def deterministic_rank(
    *,
    analysis: JobAnalysis,
    match: dict,
    catalog: list[Achievement],
    skills: list[dict],
    max_bullets: int,
) -> EvidenceRanking:
    role_family = match.get("roleFamily") or "product"
    keywords = " ".join(
        analysis.atsKeywords
        + analysis.interviewDeciders
        + [r.text for r in analysis.requirements if r.class_ in ("critical", "important")]
    ).lower()
    match_text = " ".join(
        str(m.get("requirement") or "") for m in (match.get("strongMatches") or [])
    ).lower()
    hay = f"{keywords} {match_text}"

    scored: list[RankedAchievement] = []
    for ach in catalog:
        if not ach.approvedForResume:
            continue
        base = 40.0
        statement = (ach.statement or "").lower()
        hits = sum(1 for tok in hay.split() if len(tok) > 3 and tok in statement)
        base += min(30.0, hits * 2.5)
        if ach.kind == "work":
            base += 10
        if ach.startDate:
            # Prefer recent work slightly
            try:
                year = int(str(ach.startDate)[:4])
                base += max(0, min(15, year - 2015))
            except ValueError:
                pass
        skill_boost = sum(
            3 for sid in (ach.skillIds or [])[:8] if sid and sid in hay
        )
        base += min(12, skill_boost)
        scored.append(
            RankedAchievement(
                sourceId=ach.id,
                score=min(100.0, base),
                reasons=["deterministic keyword/recency"],
            )
        )

    scored.sort(key=lambda a: a.score, reverse=True)

    by_id = {a.id: a for a in catalog}
    highlight_ids: list[str] = []
    for item in scored:
        ach = by_id.get(item.sourceId)
        if ach and ach.kind == "work" and item.sourceId not in highlight_ids:
            highlight_ids.append(item.sourceId)
        if len(highlight_ids) >= 6:
            break

    priority = PROJECT_PRIORITY.get(role_family, PROJECT_PRIORITY["product"])
    project_ids: list[str] = []
    for pid in priority:
        if any(a.kind == "project" and a.parentId == pid for a in catalog):
            project_ids.append(pid)
    for a in catalog:
        if a.kind == "project" and a.parentId not in project_ids:
            project_ids.append(a.parentId)

    skill_ids = _skill_ids_for_role(skills, role_family, limit=16)

    return EvidenceRanking(
        achievements=scored,
        skillIds=skill_ids,
        projectIds=project_ids[:8],
        recommendedBulletCap=max_bullets,
        highlightSourceIds=highlight_ids[:6],
        source="deterministic",
        provider=None,
    )


def _call_ranker(
    *,
    analysis: JobAnalysis,
    match: dict,
    catalog: list[Achievement],
    skills: list[dict],
    max_bullets: int,
) -> tuple[dict[str, Any], str]:
    catalog_slim = [
        {
            "id": a.id,
            "kind": a.kind,
            "employer": a.employer,
            "role": a.role,
            "title": a.title,
            "statement": a.statement,
            "startDate": a.startDate,
            "skillIds": a.skillIds[:8],
            "parentId": a.parentId,
        }
        for a in catalog
    ]
    skills_slim = [
        {"id": s["_id"], "name": s.get("name"), "category": s.get("category")}
        for s in skills
        if s.get("approvedForResume") and s.get("_id")
    ][:50]

    prompt = f"""Rank achievements for this role. Score each catalog item 0–100.

Positioning: {analysis.positioning}
Interview deciders: {json.dumps(analysis.interviewDeciders)}
ATS keywords: {json.dumps(analysis.atsKeywords[:25])}
Critical/important requirements: {json.dumps([r.text for r in analysis.requirements if r.class_ in ('critical', 'important')][:15])}
Match score context: {match.get('score')}/100
Strong matches: {json.dumps([m.get('requirement') for m in (match.get('strongMatches') or [])[:10]])}

Recommended bullet cap (max for resume selection): {max_bullets}

Achievement catalog (score ALL ids you can evaluate, or at least the top half):
{json.dumps(catalog_slim, indent=2)}

Approved skills:
{json.dumps(skills_slim, indent=2)}

Return JSON: achievements (sourceId, score, reasons), skillIds ranked, projectIds ranked,
recommendedBulletCap, highlightSourceIds (4-6 work sourceIds).
"""
    result = generate(
        prompt,
        system=EVIDENCE_RANKER_SYSTEM,
        temperature=0.15,
        process="evidenceRanker",
        response_format=EVIDENCE_RANKER_SCHEMA,
    )
    parsed = extract_json(result.text)
    if not isinstance(parsed, dict):
        raise ValueError("evidence ranker response was not a JSON object")
    return parsed, result.provider


def _normalize_ranking(
    raw: dict[str, Any],
    *,
    by_id: dict[str, Achievement],
    approved_skill_ids: set[str],
    max_bullets: int,
    provider: str | None,
    source: str,
) -> EvidenceRanking:
    achievements: list[RankedAchievement] = []
    seen: set[str] = set()
    for item in raw.get("achievements") or []:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("sourceId") or "").strip()
        if sid not in by_id or sid in seen:
            continue
        seen.add(sid)
        try:
            score = float(item.get("score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        score = max(0.0, min(100.0, score))
        reasons = [
            str(r).strip()
            for r in (item.get("reasons") or [])
            if str(r).strip()
        ][:4]
        achievements.append(
            RankedAchievement(sourceId=sid, score=score, reasons=reasons)
        )

    # Ensure unscored catalog items appear with low scores so composer still has a full list
    for sid, ach in by_id.items():
        if sid not in seen:
            achievements.append(
                RankedAchievement(
                    sourceId=sid, score=10.0, reasons=["unscored"]
                )
            )

    achievements.sort(key=lambda a: a.score, reverse=True)

    skill_ids: list[str] = []
    for sid in raw.get("skillIds") or []:
        sid = str(sid).strip()
        if sid in approved_skill_ids and sid not in skill_ids:
            skill_ids.append(sid)

    project_ids: list[str] = []
    for pid in raw.get("projectIds") or []:
        pid = str(pid).strip()
        if pid and pid not in project_ids:
            if any(a.kind == "project" and a.parentId == pid for a in by_id.values()):
                project_ids.append(pid)

    highlight_ids: list[str] = []
    for sid in raw.get("highlightSourceIds") or []:
        sid = str(sid).strip()
        ach = by_id.get(sid)
        if ach and ach.kind == "work" and sid not in highlight_ids:
            highlight_ids.append(sid)
        if len(highlight_ids) >= 6:
            break
    if len(highlight_ids) < 4:
        for item in achievements:
            ach = by_id.get(item.sourceId)
            if ach and ach.kind == "work" and item.sourceId not in highlight_ids:
                highlight_ids.append(item.sourceId)
            if len(highlight_ids) >= 6:
                break

    cap = raw.get("recommendedBulletCap")
    try:
        recommended = int(cap) if cap is not None else max_bullets
    except (TypeError, ValueError):
        recommended = max_bullets
    recommended = max(4, min(max_bullets, recommended))

    return EvidenceRanking(
        achievements=achievements,
        skillIds=skill_ids[:20],
        projectIds=project_ids[:10],
        recommendedBulletCap=recommended,
        highlightSourceIds=highlight_ids[:6],
        source=source,
        provider=provider,
    )


def _skill_ids_for_role(
    skills: list[dict], role_family: str, limit: int = 16
) -> list[str]:
    if role_family == "systems":
        categories = ["systems", "iac", "devops", "cicd", "cloud", "data", "languages"]
    elif role_family == "mobile":
        categories = ["mobile", "media", "languages", "cloud", "backend"]
    elif role_family == "ai":
        categories = ["ai", "backend", "cloud", "languages", "frontend"]
    else:
        categories = ["frontend", "product", "backend", "cloud", "languages", "auth"]

    ids: list[str] = []
    for cat in categories:
        for skill in skills:
            if (
                skill.get("approvedForResume")
                and skill.get("category") == cat
                and skill.get("_id")
                and skill["_id"] not in ids
            ):
                ids.append(skill["_id"])
            if len(ids) >= limit:
                return ids
    for skill in skills:
        if (
            skill.get("approvedForResume")
            and skill.get("_id")
            and skill["_id"] not in ids
        ):
            ids.append(skill["_id"])
        if len(ids) >= limit:
            break
    return ids
