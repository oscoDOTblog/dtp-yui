"""Ollama select+rewrite with sourceId grounding and Pydantic verification."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from ..llm import generate
from ..ollama_client import extract_json
from .achievements import Achievement, catalog_by_id

logger = logging.getLogger(__name__)

RESUME_TAILOR_SYSTEM = """You tailor a resume by selecting and lightly rewriting approved achievements.
Use ONLY achievements from the provided catalog. Every rewritten bullet MUST include a sourceId
from the catalog. Never invent employers, tools, metrics, or outcomes not present in the source.
Allowed rewrites: shorten, emphasize relevant skills already listed, convert to action-result tone.
Return JSON only matching the schema. Do not invent achievement IDs.
"""

DEFAULT_SECTION_ORDER = [
    "summary",
    "skills",
    "experience",
    "projects",
    "education",
]

MAX_BULLETS_BY_PAGES = {1: 8, 2: 12}

PROJECT_PRIORITY = {
    "systems": ["project_sway_sls", "project_videodl", "project_swayquest_web"],
    "mobile": ["project_ios_player", "project_android_player", "project_sway_pocket"],
    "ai": ["project_swayquest_web", "project_sway_sls", "project_sway_pocket"],
    "product": ["project_swayquest_web", "project_sway_pocket", "project_sway_sls"],
}

TAILOR_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "targetRole": {"type": "string"},
        "summary": {"type": "string"},
        "selectedAchievementIds": {
            "type": "array",
            "items": {"type": "string"},
        },
        "rewrittenAchievements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sourceId": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["sourceId", "text"],
            },
        },
        "selectedSkillIds": {"type": "array", "items": {"type": "string"}},
        "selectedProjectIds": {"type": "array", "items": {"type": "string"}},
        "omittedRequirements": {"type": "array", "items": {"type": "string"}},
        "sectionOrder": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "targetRole",
        "summary",
        "selectedAchievementIds",
        "rewrittenAchievements",
        "selectedSkillIds",
        "selectedProjectIds",
        "omittedRequirements",
    ],
}


class RewrittenAchievement(BaseModel):
    sourceId: str
    text: str


class TailorPayload(BaseModel):
    targetRole: str = ""
    summary: str = ""
    selectedAchievementIds: list[str] = Field(default_factory=list)
    rewrittenAchievements: list[RewrittenAchievement] = Field(default_factory=list)
    selectedSkillIds: list[str] = Field(default_factory=list)
    selectedProjectIds: list[str] = Field(default_factory=list)
    omittedRequirements: list[str] = Field(default_factory=list)
    sectionOrder: list[str] = Field(default_factory=lambda: list(DEFAULT_SECTION_ORDER))
    usedLlm: bool = False
    fallbackReason: str | None = None
    provider: str | None = None  # "openai" | "ollama" when usedLlm

    def rewrite_map(self) -> dict[str, str]:
        return {r.sourceId: r.text for r in self.rewrittenAchievements}

    def to_report(self) -> dict[str, Any]:
        return {
            "targetRole": self.targetRole,
            "summary": self.summary,
            "selectedAchievementIds": list(self.selectedAchievementIds),
            "rewrittenAchievements": [r.model_dump() for r in self.rewrittenAchievements],
            "selectedSkillIds": list(self.selectedSkillIds),
            "selectedProjectIds": list(self.selectedProjectIds),
            "omittedRequirements": list(self.omittedRequirements),
            "sectionOrder": list(self.sectionOrder),
            "usedLlm": self.usedLlm,
            "fallbackReason": self.fallbackReason,
            "provider": self.provider,
            "bulletCount": len(self.selectedAchievementIds),
        }


def tailor_resume(
    *,
    candidate: dict,
    job: dict,
    match: dict,
    catalog: list[Achievement],
    skills: list[dict],
    pages: Literal[1, 2] = 2,
) -> TailorPayload:
    """Select + rewrite achievements; always returns a verified payload."""
    max_bullets = MAX_BULLETS_BY_PAGES.get(pages, 12)
    approved = [a for a in catalog if a.approvedForResume]
    by_id = catalog_by_id(approved)
    approved_skill_ids = {
        s["_id"] for s in skills if s.get("approvedForResume") and s.get("_id")
    }

    try:
        raw, provider = _call_llm_tailor(
            candidate=candidate,
            job=job,
            match=match,
            catalog=approved,
            skills=skills,
            max_bullets=max_bullets,
        )
        payload = verify_tailor_payload(
            raw,
            by_id=by_id,
            approved_skill_ids=approved_skill_ids,
            max_bullets=max_bullets,
            used_llm=True,
            provider=provider,
        )
        if payload.selectedAchievementIds:
            return payload
        logger.warning("LLM tailor produced empty selection; using fallback")
        return deterministic_fallback(
            candidate=candidate,
            job=job,
            match=match,
            catalog=approved,
            skills=skills,
            max_bullets=max_bullets,
            reason="empty_llm_selection",
        )
    except Exception as exc:
        logger.warning("Resume tailor LLM failed, using fallback: %s", exc)
        return deterministic_fallback(
            candidate=candidate,
            job=job,
            match=match,
            catalog=approved,
            skills=skills,
            max_bullets=max_bullets,
            reason=str(exc)[:240],
        )


def verify_tailor_payload(
    raw: dict[str, Any] | TailorPayload,
    *,
    by_id: dict[str, Achievement],
    approved_skill_ids: set[str],
    max_bullets: int,
    used_llm: bool,
    provider: str | None = None,
) -> TailorPayload:
    if isinstance(raw, TailorPayload):
        data = raw.model_dump()
    else:
        try:
            data = TailorPayload.model_validate(raw).model_dump()
        except ValidationError:
            # Partial / messy JSON — coerce what we can
            data = dict(raw or {})

    employers = {
        (a.employer or "").strip()
        for a in by_id.values()
        if (a.employer or "").strip()
    }

    selected_ids: list[str] = []
    for aid in data.get("selectedAchievementIds") or []:
        aid = str(aid).strip()
        if aid in by_id and aid not in selected_ids:
            selected_ids.append(aid)

    rewrite_raw = {
        str(item.get("sourceId") or "").strip(): str(item.get("text") or "").strip()
        for item in (data.get("rewrittenAchievements") or [])
        if isinstance(item, dict)
    }
    # Also accept ids only present in rewrites
    for sid in rewrite_raw:
        if sid in by_id and sid not in selected_ids:
            selected_ids.append(sid)

    selected_ids = selected_ids[:max_bullets]

    rewritten: list[RewrittenAchievement] = []
    for sid in selected_ids:
        ach = by_id[sid]
        text = rewrite_raw.get(sid) or ach.statement
        if not text.strip():
            text = ach.statement
        if not _rewrite_is_safe(text, ach, employers):
            text = ach.statement
        rewritten.append(RewrittenAchievement(sourceId=sid, text=text.strip()))

    skill_ids: list[str] = []
    for sid in data.get("selectedSkillIds") or []:
        sid = str(sid).strip()
        if sid in approved_skill_ids and sid not in skill_ids:
            skill_ids.append(sid)

    project_ids: list[str] = []
    for pid in data.get("selectedProjectIds") or []:
        pid = str(pid).strip()
        if pid and pid not in project_ids:
            # Only keep projects that appear in selected achievements
            if any(
                by_id[a].kind == "project" and by_id[a].parentId == pid
                for a in selected_ids
            ):
                project_ids.append(pid)
    if not project_ids:
        for sid in selected_ids:
            ach = by_id[sid]
            if ach.kind == "project" and ach.parentId not in project_ids:
                project_ids.append(ach.parentId)

    section_order = [
        s for s in (data.get("sectionOrder") or DEFAULT_SECTION_ORDER) if isinstance(s, str)
    ] or list(DEFAULT_SECTION_ORDER)

    omitted = [
        str(x).strip()
        for x in (data.get("omittedRequirements") or [])
        if str(x).strip()
    ][:12]

    return TailorPayload(
        targetRole=str(data.get("targetRole") or "").strip(),
        summary=str(data.get("summary") or "").strip(),
        selectedAchievementIds=selected_ids,
        rewrittenAchievements=rewritten,
        selectedSkillIds=skill_ids,
        selectedProjectIds=project_ids,
        omittedRequirements=omitted,
        sectionOrder=section_order,
        usedLlm=used_llm,
        fallbackReason=None,
        provider=provider if used_llm else None,
    )


def deterministic_fallback(
    *,
    candidate: dict,
    job: dict,
    match: dict,
    catalog: list[Achievement],
    skills: list[dict],
    max_bullets: int,
    reason: str,
) -> TailorPayload:
    role_family = match.get("roleFamily") or "product"
    positioning = (candidate.get("positioningSummaries") or {}).get(
        role_family
    ) or (candidate.get("positioningSummaries") or {}).get("product", "")

    work = [a for a in catalog if a.kind == "work"]
    projects = [a for a in catalog if a.kind == "project"]

    # Prefer more recent work (by startDate on achievement)
    work_sorted = sorted(work, key=lambda a: a.startDate or "", reverse=True)
    priority = PROJECT_PRIORITY.get(
        role_family, PROJECT_PRIORITY["product"]
    )
    projects_sorted: list[Achievement] = []
    seen_p: set[str] = set()
    for pid in priority:
        for a in projects:
            if a.parentId == pid and a.id not in seen_p:
                projects_sorted.append(a)
                seen_p.add(a.id)
    for a in projects:
        if a.id not in seen_p:
            projects_sorted.append(a)
            seen_p.add(a.id)

    selected: list[Achievement] = []
    # Roughly half work / half projects, work first
    work_cap = max(4, max_bullets // 2 + 1)
    for a in work_sorted:
        if len(selected) >= work_cap:
            break
        selected.append(a)
    for a in projects_sorted:
        if len(selected) >= max_bullets:
            break
        selected.append(a)
    selected = selected[:max_bullets]

    skill_ids = _fallback_skill_ids(skills, role_family, limit=14)
    project_ids: list[str] = []
    for a in selected:
        if a.kind == "project" and a.parentId not in project_ids:
            project_ids.append(a.parentId)

    omitted = [
        str(g.get("skill") or g.get("requirement") or "").strip()
        for g in (match.get("meaningfulGaps") or [])
        if str(g.get("skill") or g.get("requirement") or "").strip()
    ][:8]

    return TailorPayload(
        targetRole=str(job.get("title") or "").strip(),
        summary=str(positioning or "").strip(),
        selectedAchievementIds=[a.id for a in selected],
        rewrittenAchievements=[
            RewrittenAchievement(sourceId=a.id, text=a.statement) for a in selected
        ],
        selectedSkillIds=skill_ids,
        selectedProjectIds=project_ids,
        omittedRequirements=omitted,
        sectionOrder=list(DEFAULT_SECTION_ORDER),
        usedLlm=False,
        fallbackReason=reason,
    )


def gaps_markdown(match: dict, payload: TailorPayload) -> str:
    lines = [
        f"# Gaps — {payload.targetRole or 'role'}",
        "",
        "## Meaningful match gaps",
    ]
    gaps = match.get("meaningfulGaps") or []
    if gaps:
        for g in gaps[:10]:
            skill = g.get("skill") or g.get("requirement") or "gap"
            reason = g.get("reason") or ""
            lines.append(f"- **{skill}**: {reason}")
    else:
        lines.append("- None flagged.")

    lines += ["", "## Omitted JD requirements (tailor)"]
    if payload.omittedRequirements:
        for item in payload.omittedRequirements:
            lines.append(f"- {item}")
    else:
        lines.append("- None listed.")

    lines += [
        "",
        f"Tailor used LLM: **{payload.usedLlm}**",
    ]
    if payload.provider:
        lines.append(f"Provider: **{payload.provider}**")
    if payload.fallbackReason:
        lines.append(f"Fallback reason: {payload.fallbackReason}")
    return "\n".join(lines) + "\n"


def _call_llm_tailor(
    *,
    candidate: dict,
    job: dict,
    match: dict,
    catalog: list[Achievement],
    skills: list[dict],
    max_bullets: int,
) -> tuple[dict[str, Any], str]:
    role_family = match.get("roleFamily") or "product"
    positioning = (candidate.get("positioningSummaries") or {}).get(
        role_family
    ) or ""

    catalog_slim = [
        {
            "id": a.id,
            "kind": a.kind,
            "employer": a.employer,
            "role": a.role,
            "title": a.title,
            "statement": a.statement,
            "skillIds": a.skillIds[:8],
            "categories": a.categories,
        }
        for a in catalog
    ]
    skills_slim = [
        {"id": s["_id"], "name": s.get("name"), "category": s.get("category")}
        for s in skills
        if s.get("approvedForResume") and s.get("_id")
    ][:40]

    prompt = f"""Tailor a resume for this job. Select at most {max_bullets} achievements.

Candidate: {candidate.get('name')}
Role family emphasis: {role_family}
Default positioning summary (adapt lightly, do not invent facts): {positioning}

Target job:
Title: {job.get('title')}
Company: {job.get('company')}
Match score: {match.get('score')}/100 ({match.get('recommendation')})
Strong matches: {json.dumps([m.get('requirement') for m in (match.get('strongMatches') or [])[:10]])}
Meaningful gaps: {json.dumps([g.get('skill') for g in (match.get('meaningfulGaps') or [])[:8]])}

Job description (truncated):
{(job.get('descriptionRaw') or '')[:3500]}

Achievement catalog (ONLY use these ids):
{json.dumps(catalog_slim, indent=2)}

Approved skills:
{json.dumps(skills_slim, indent=2)}

Return JSON with targetRole, summary, selectedAchievementIds, rewrittenAchievements
(sourceId+text), selectedSkillIds, selectedProjectIds, omittedRequirements, sectionOrder.
"""
    result = generate(
        prompt,
        system=RESUME_TAILOR_SYSTEM,
        temperature=0.2,
        process="resumeTailor",
        response_format=TAILOR_JSON_SCHEMA,
    )
    parsed = extract_json(result.text)
    if not isinstance(parsed, dict):
        raise ValueError("tailor response was not a JSON object")
    return parsed, result.provider


def _rewrite_is_safe(
    text: str, source: Achievement, all_employers: set[str]
) -> bool:
    """Reject rewrites that introduce another catalog employer name."""
    if not text or not text.strip():
        return False
    lower = text.lower()
    source_employer = (source.employer or "").strip().lower()
    for emp in all_employers:
        emp_l = emp.lower()
        if len(emp_l) < 3:
            continue
        if emp_l == source_employer:
            continue
        if emp_l == "independent":
            continue
        # Word-boundary-ish check
        if re.search(rf"(?<![a-z]){re.escape(emp_l)}(?![a-z])", lower):
            return False
    return True


def _fallback_skill_ids(
    skills: list[dict], role_family: str, limit: int = 14
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
