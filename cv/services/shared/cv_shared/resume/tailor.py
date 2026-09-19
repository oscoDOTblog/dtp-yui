"""Resume select+rewrite with sourceId grounding and Pydantic verification."""

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

# Prefer shared composer system when multi-stage context is available
try:
    from ..package.prompts import RESUME_COMPOSER_SYSTEM

    RESUME_TAILOR_SYSTEM = RESUME_COMPOSER_SYSTEM
except Exception:  # pragma: no cover
    RESUME_TAILOR_SYSTEM = """You tailor a resume by selecting and lightly rewriting approved achievements.
Use ONLY achievements from the provided catalog. Every rewritten bullet MUST include a sourceId
from the catalog. Never invent employers, tools, metrics, or outcomes not present in the source.
Allowed rewrites: shorten, emphasize relevant skills already listed, convert to action-result tone.
Return JSON only matching the schema. Do not invent achievement IDs.
"""

DEFAULT_SECTION_ORDER = [
    "summary",
    "highlights",
    "skills",
    "experience",
    "projects",
    "technologies",
    "education",
]

MAX_BULLETS_BY_PAGES = {1: 8, 2: 12}
MAX_HIGHLIGHTS = 6
MAX_SKILLS = 24
MIN_PROJECT_BULLETS = {1: 2, 2: 4}  # two-page dual profile floor
MIN_PROJECTS = {1: 1, 2: 2}

PROJECT_PRIORITY = {
    "systems": ["project_sway_sls", "project_videodl", "project_swayquest_web"],
    "mobile": ["project_ios_player", "project_android_player", "project_sway_pocket"],
    "ai": ["project_swayquest_web", "project_sway_sls", "project_sway_pocket"],
    "product": ["project_swayquest_web", "project_sway_pocket", "project_sway_sls"],
}

_REWRITTEN_ITEM = {
    "type": "object",
    "properties": {
        "sourceId": {"type": "string"},
        "text": {"type": "string"},
    },
    "required": ["sourceId", "text"],
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
            "items": _REWRITTEN_ITEM,
        },
        "highlights": {
            "type": "array",
            "items": _REWRITTEN_ITEM,
        },
        "selectedSkillIds": {"type": "array", "items": {"type": "string"}},
        "selectedProjectIds": {"type": "array", "items": {"type": "string"}},
        "skillsGrouped": {
            "type": "object",
            "additionalProperties": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "omittedRequirements": {"type": "array", "items": {"type": "string"}},
        "sectionOrder": {"type": "array", "items": {"type": "string"}},
        "professionalTitle": {"type": "string"},
        "specialtyLine": {"type": "string"},
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
    highlights: list[RewrittenAchievement] = Field(default_factory=list)
    selectedSkillIds: list[str] = Field(default_factory=list)
    selectedProjectIds: list[str] = Field(default_factory=list)
    skillsGrouped: dict[str, list[str]] = Field(default_factory=dict)
    omittedRequirements: list[str] = Field(default_factory=list)
    sectionOrder: list[str] = Field(default_factory=lambda: list(DEFAULT_SECTION_ORDER))
    professionalTitle: str = ""
    specialtyLine: str = ""
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
            "highlights": [r.model_dump() for r in self.highlights],
            "selectedSkillIds": list(self.selectedSkillIds),
            "selectedProjectIds": list(self.selectedProjectIds),
            "skillsGrouped": dict(self.skillsGrouped),
            "omittedRequirements": list(self.omittedRequirements),
            "sectionOrder": list(self.sectionOrder),
            "professionalTitle": self.professionalTitle,
            "specialtyLine": self.specialtyLine,
            "usedLlm": self.usedLlm,
            "fallbackReason": self.fallbackReason,
            "provider": self.provider,
            "bulletCount": len(self.selectedAchievementIds),
            "highlightCount": len(self.highlights),
        }


def tailor_resume(
    *,
    candidate: dict,
    job: dict,
    match: dict,
    catalog: list[Achievement],
    skills: list[dict],
    pages: Literal[1, 2] = 2,
    analysis: dict[str, Any] | None = None,
    ranking: dict[str, Any] | None = None,
    max_bullets_override: int | None = None,
    critic_feedback: str | None = None,
    work_history: list[dict] | None = None,
    projects: list[dict] | None = None,
) -> TailorPayload:
    """Select + rewrite achievements; always returns a verified payload."""
    max_bullets = max_bullets_override or MAX_BULLETS_BY_PAGES.get(pages, 12)
    max_bullets = max(4, min(MAX_BULLETS_BY_PAGES.get(pages, 12), max_bullets))
    approved = [a for a in catalog if a.approvedForResume]
    by_id = catalog_by_id(approved)
    approved_skill_ids = {
        s["_id"] for s in skills if s.get("approvedForResume") and s.get("_id")
    }
    work_history = work_history or []
    projects = projects or []
    role_family = match.get("roleFamily") or "product"

    try:
        raw, provider = _call_llm_tailor(
            candidate=candidate,
            job=job,
            match=match,
            catalog=approved,
            skills=skills,
            max_bullets=max_bullets,
            analysis=analysis,
            ranking=ranking,
            critic_feedback=critic_feedback,
            pages=pages,
        )
        payload = verify_tailor_payload(
            raw,
            by_id=by_id,
            approved_skill_ids=approved_skill_ids,
            max_bullets=max_bullets,
            used_llm=True,
            provider=provider,
            skills=skills,
            ranking=ranking,
        )
        if payload.selectedAchievementIds:
            return finalize_resume_payload(
                payload,
                candidate=candidate,
                catalog=approved,
                skills=skills,
                work_history=work_history,
                projects=projects,
                max_bullets=max_bullets,
                pages=pages,
                role_family=role_family,
                ranking=ranking,
            )
        logger.warning("LLM tailor produced empty selection; using fallback")
        payload = deterministic_fallback(
            candidate=candidate,
            job=job,
            match=match,
            catalog=approved,
            skills=skills,
            max_bullets=max_bullets,
            reason="empty_llm_selection",
            ranking=ranking,
            analysis=analysis,
        )
        return finalize_resume_payload(
            payload,
            candidate=candidate,
            catalog=approved,
            skills=skills,
            work_history=work_history,
            projects=projects,
            max_bullets=max_bullets,
            pages=pages,
            role_family=role_family,
            ranking=ranking,
        )
    except Exception as exc:
        logger.warning("Resume tailor LLM failed, using fallback: %s", exc)
        payload = deterministic_fallback(
            candidate=candidate,
            job=job,
            match=match,
            catalog=approved,
            skills=skills,
            max_bullets=max_bullets,
            reason=str(exc)[:240],
            ranking=ranking,
            analysis=analysis,
        )
        return finalize_resume_payload(
            payload,
            candidate=candidate,
            catalog=approved,
            skills=skills,
            work_history=work_history,
            projects=projects,
            max_bullets=max_bullets,
            pages=pages,
            role_family=role_family,
            ranking=ranking,
        )


def verify_tailor_payload(
    raw: dict[str, Any] | TailorPayload,
    *,
    by_id: dict[str, Achievement],
    approved_skill_ids: set[str],
    max_bullets: int,
    used_llm: bool,
    provider: str | None = None,
    skills: list[dict] | None = None,
    ranking: dict[str, Any] | None = None,
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

    # Highlights (optional, max 6)
    highlight_raw = {
        str(item.get("sourceId") or "").strip(): str(item.get("text") or "").strip()
        for item in (data.get("highlights") or [])
        if isinstance(item, dict)
    }
    highlight_ids: list[str] = []
    for sid in highlight_raw:
        if sid in by_id and sid not in highlight_ids:
            highlight_ids.append(sid)
    # Prefer ranking highlight suggestions when model omitted them
    if len(highlight_ids) < 4 and ranking:
        for sid in ranking.get("highlightSourceIds") or []:
            sid = str(sid).strip()
            if sid in by_id and by_id[sid].kind == "work" and sid not in highlight_ids:
                highlight_ids.append(sid)
            if len(highlight_ids) >= MAX_HIGHLIGHTS:
                break
    if len(highlight_ids) < 4:
        for sid in selected_ids:
            if by_id[sid].kind == "work" and sid not in highlight_ids:
                highlight_ids.append(sid)
            if len(highlight_ids) >= MAX_HIGHLIGHTS:
                break
    highlight_ids = highlight_ids[:MAX_HIGHLIGHTS]

    highlights: list[RewrittenAchievement] = []
    for sid in highlight_ids:
        ach = by_id[sid]
        text = highlight_raw.get(sid) or rewrite_raw.get(sid) or ach.statement
        if not text.strip():
            text = ach.statement
        if not _rewrite_is_safe(text, ach, employers):
            text = ach.statement
        highlights.append(RewrittenAchievement(sourceId=sid, text=text.strip()))

    skill_ids: list[str] = []
    for sid in data.get("selectedSkillIds") or []:
        sid = str(sid).strip()
        if sid in approved_skill_ids and sid not in skill_ids:
            skill_ids.append(sid)
    # Prefer ranked skills when empty
    if not skill_ids and ranking:
        for sid in ranking.get("skillIds") or []:
            sid = str(sid).strip()
            if sid in approved_skill_ids and sid not in skill_ids:
                skill_ids.append(sid)

    skills_grouped: dict[str, list[str]] = {}
    raw_grouped = data.get("skillsGrouped") or {}
    if isinstance(raw_grouped, dict):
        for cat, ids in raw_grouped.items():
            cat_name = str(cat or "").strip()
            if not cat_name or not isinstance(ids, list):
                continue
            clean: list[str] = []
            for sid in ids:
                sid = str(sid).strip()
                if sid in approved_skill_ids and sid not in clean:
                    clean.append(sid)
            if clean:
                skills_grouped[cat_name] = clean
                for sid in clean:
                    if sid not in skill_ids:
                        skill_ids.append(sid)

    skill_ids = skill_ids[:MAX_SKILLS]
    if not skills_grouped and skill_ids and skills:
        skills_grouped = _group_skills_by_category(skills, skill_ids)

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
    for required in ("technologies", "highlights"):
        if required not in section_order:
            if required == "highlights" and "summary" in section_order:
                section_order.insert(section_order.index("summary") + 1, "highlights")
            elif required == "technologies" and "projects" in section_order:
                section_order.insert(section_order.index("projects") + 1, "technologies")
            elif required not in section_order:
                section_order.append(required)

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
        highlights=highlights,
        selectedSkillIds=skill_ids,
        selectedProjectIds=project_ids,
        skillsGrouped=skills_grouped,
        omittedRequirements=omitted,
        sectionOrder=section_order,
        professionalTitle=str(data.get("professionalTitle") or "").strip(),
        specialtyLine=str(data.get("specialtyLine") or "").strip(),
        usedLlm=used_llm,
        fallbackReason=None,
        provider=provider if used_llm else None,
    )


def finalize_resume_payload(
    payload: TailorPayload,
    *,
    candidate: dict,
    catalog: list[Achievement],
    skills: list[dict],
    work_history: list[dict],
    projects: list[dict],
    max_bullets: int,
    pages: Literal[1, 2] = 2,
    role_family: str = "product",
    ranking: dict[str, Any] | None = None,
) -> TailorPayload:
    """Post-verify layout enrichments: project floor, skill ceiling, milestones, header."""
    by_id = catalog_by_id(catalog)
    approved_skill_ids = {
        s["_id"] for s in skills if s.get("approvedForResume") and s.get("_id")
    }

    selected = list(payload.selectedAchievementIds)
    rewrite_map = payload.rewrite_map()

    min_project_bullets = MIN_PROJECT_BULLETS.get(pages, 4)
    min_projects = MIN_PROJECTS.get(pages, 2)
    selected = _ensure_project_floor(
        selected_ids=selected,
        by_id=by_id,
        max_bullets=max_bullets,
        min_project_bullets=min_project_bullets,
        min_projects=min_projects,
        role_family=role_family,
        ranking=ranking,
    )

    # Rebuild rewrite list for any newly added achievements
    rewritten: list[RewrittenAchievement] = []
    for sid in selected:
        if sid not in by_id:
            continue
        text = rewrite_map.get(sid) or by_id[sid].statement
        rewritten.append(RewrittenAchievement(sourceId=sid, text=text.strip()))

    project_ids: list[str] = []
    for sid in selected:
        ach = by_id.get(sid)
        if ach and ach.kind == "project" and ach.parentId not in project_ids:
            project_ids.append(ach.parentId)

    # Broader skill ceiling; always rebalance so product languages survive systems bias
    skill_ids = _expand_skills(
        list(payload.selectedSkillIds),
        skills=skills,
        approved_skill_ids=approved_skill_ids,
        role_family=role_family,
        ranking=ranking,
        limit=MAX_SKILLS,
    )
    skills_grouped = _group_skills_by_category(skills, skill_ids)

    # Header fields
    professional_title = (
        payload.professionalTitle
        or str(candidate.get("professionalTitle") or "").strip()
        or "Principal Software Engineer"
    )
    specialty = (
        payload.specialtyLine
        or str(candidate.get("specialtyLine") or "").strip()
        or "Distributed Systems • Cloud Infrastructure • AI Platforms • Full-Stack Product Engineering"
    )

    # Milestone highlights (deterministic); still keep safe grounded text only
    from .layout import apply_milestone_highlights

    # Temporarily assign selection so milestone helper can read it
    temp = payload.model_copy(
        update={
            "selectedAchievementIds": selected,
            "rewrittenAchievements": rewritten,
        }
    )
    milestones = apply_milestone_highlights(
        payload=temp,
        catalog=catalog,
        work_history=work_history,
        projects=projects,
    )
    highlights = milestones if milestones else list(payload.highlights)

    section_order = list(payload.sectionOrder or DEFAULT_SECTION_ORDER)
    if "technologies" not in section_order:
        if "projects" in section_order:
            section_order.insert(section_order.index("projects") + 1, "technologies")
        else:
            section_order.append("technologies")

    return payload.model_copy(
        update={
            "selectedAchievementIds": selected,
            "rewrittenAchievements": rewritten,
            "highlights": highlights,
            "selectedSkillIds": skill_ids,
            "selectedProjectIds": project_ids,
            "skillsGrouped": skills_grouped,
            "professionalTitle": professional_title,
            "specialtyLine": specialty,
            "sectionOrder": section_order,
        }
    )


def _ensure_project_floor(
    *,
    selected_ids: list[str],
    by_id: dict[str, Achievement],
    max_bullets: int,
    min_project_bullets: int,
    min_projects: int,
    role_family: str,
    ranking: dict[str, Any] | None,
) -> list[str]:
    catalog_projects = [a for a in by_id.values() if a.kind == "project"]
    if not catalog_projects:
        return selected_ids

    selected = list(selected_ids)

    def project_count(ids: list[str]) -> int:
        return sum(1 for sid in ids if by_id.get(sid) and by_id[sid].kind == "project")

    def project_parent_count(ids: list[str]) -> int:
        parents: set[str] = set()
        for sid in ids:
            ach = by_id.get(sid)
            if ach and ach.kind == "project":
                parents.add(ach.parentId)
        return len(parents)

    if (
        project_count(selected) >= min_project_bullets
        and project_parent_count(selected) >= min_projects
    ):
        return selected[:max_bullets]

    # Order available project achievements by ranking then PROJECT_PRIORITY
    ranked_ids: list[str] = []
    if ranking and ranking.get("achievements"):
        ordered = sorted(
            ranking["achievements"],
            key=lambda a: float(a.get("score") or 0),
            reverse=True,
        )
        for item in ordered:
            sid = str(item.get("sourceId") or "")
            if sid in by_id and by_id[sid].kind == "project" and sid not in ranked_ids:
                ranked_ids.append(sid)

    priority = PROJECT_PRIORITY.get(role_family, PROJECT_PRIORITY["product"])
    for pid in priority:
        for a in catalog_projects:
            if a.parentId == pid and a.id not in ranked_ids:
                ranked_ids.append(a.id)
    for a in catalog_projects:
        if a.id not in ranked_ids:
            ranked_ids.append(a.id)

    selected_set = set(selected)
    for sid in ranked_ids:
        if (
            project_count(selected) >= min_project_bullets
            and project_parent_count(selected) >= min_projects
        ):
            break
        if sid in selected_set:
            continue
        if len(selected) >= max_bullets:
            # Drop last work bullet to make room (keep at least 3 work if available)
            work_idxs = [
                i
                for i, x in enumerate(selected)
                if by_id.get(x) and by_id[x].kind == "work"
            ]
            if len(work_idxs) <= 3:
                break
            drop_i = work_idxs[-1]
            selected_set.discard(selected[drop_i])
            selected.pop(drop_i)
        selected.append(sid)
        selected_set.add(sid)

    return selected[:max_bullets]


def _expand_skills(
    skill_ids: list[str],
    *,
    skills: list[dict],
    approved_skill_ids: set[str],
    role_family: str,
    ranking: dict[str, Any] | None,
    limit: int,
) -> list[str]:
    """Build skill list with role bias + reserved product/language slots."""
    reserved: list[str] = []
    reserve_cats = ["languages", "frontend", "mobile", "ai", "backend"]
    for cat in reserve_cats:
        for skill in skills:
            sid = skill.get("_id")
            if (
                skill.get("approvedForResume")
                and skill.get("category") == cat
                and sid in approved_skill_ids
                and sid not in reserved
            ):
                reserved.append(sid)
            if len(reserved) >= 8:
                break
        if len(reserved) >= 8:
            break

    primary: list[str] = []
    for sid in skill_ids:
        if sid in approved_skill_ids and sid not in primary and sid not in reserved:
            primary.append(sid)

    if ranking:
        for sid in ranking.get("skillIds") or []:
            sid = str(sid).strip()
            if sid in approved_skill_ids and sid not in primary and sid not in reserved:
                primary.append(sid)

    primary_cats = {
        "systems": [
            "systems",
            "iac",
            "devops",
            "cicd",
            "cloud",
            "data",
            "observability",
            "backend",
            "languages",
        ],
        "mobile": ["mobile", "media", "languages", "cloud", "backend", "frontend"],
        "ai": ["ai", "backend", "cloud", "languages", "frontend", "product"],
        "product": [
            "frontend",
            "product",
            "backend",
            "cloud",
            "languages",
            "auth",
            "mobile",
            "ai",
        ],
    }
    categories = primary_cats.get(role_family, primary_cats["product"])
    room = max(0, limit - len(reserved))
    for cat in categories:
        for skill in skills:
            sid = skill.get("_id")
            if (
                skill.get("approvedForResume")
                and skill.get("category") == cat
                and sid in approved_skill_ids
                and sid not in primary
                and sid not in reserved
            ):
                primary.append(sid)
            if len(primary) >= room:
                break
        if len(primary) >= room:
            break

    primary = primary[:room]
    out = list(reserved[:6]) + primary + reserved[6:]
    seen: set[str] = set()
    final: list[str] = []
    for sid in out:
        if sid in seen:
            continue
        seen.add(sid)
        final.append(sid)
        if len(final) >= limit:
            break
    return final


def deterministic_fallback(
    *,
    candidate: dict,
    job: dict,
    match: dict,
    catalog: list[Achievement],
    skills: list[dict],
    max_bullets: int,
    reason: str,
    ranking: dict[str, Any] | None = None,
    analysis: dict[str, Any] | None = None,
) -> TailorPayload:
    role_family = match.get("roleFamily") or "product"
    positioning = (candidate.get("positioningSummaries") or {}).get(
        role_family
    ) or (candidate.get("positioningSummaries") or {}).get("product", "")
    if analysis and analysis.get("positioning"):
        target_role = str(analysis["positioning"])
    else:
        target_role = str(job.get("title") or "").strip()

    by_id = catalog_by_id(catalog)
    selected: list[Achievement] = []

    if ranking and ranking.get("achievements"):
        ordered = sorted(
            ranking["achievements"],
            key=lambda a: float(a.get("score") or 0),
            reverse=True,
        )
        for item in ordered:
            sid = str(item.get("sourceId") or "")
            if sid in by_id and by_id[sid] not in selected:
                selected.append(by_id[sid])
            if len(selected) >= max_bullets:
                break

    if not selected:
        work = [a for a in catalog if a.kind == "work"]
        projects = [a for a in catalog if a.kind == "project"]
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

    skill_ids: list[str] = []
    if ranking and ranking.get("skillIds"):
        approved = {
            s["_id"] for s in skills if s.get("approvedForResume") and s.get("_id")
        }
        for sid in ranking["skillIds"]:
            if sid in approved and sid not in skill_ids:
                skill_ids.append(sid)
    if not skill_ids:
        skill_ids = _fallback_skill_ids(skills, role_family, limit=MAX_SKILLS)

    # Ensure dual-profile project mix in deterministic path
    work_only = [a for a in selected if a.kind == "work"]
    project_only = [a for a in selected if a.kind == "project"]
    min_p = MIN_PROJECT_BULLETS.get(2, 4)
    if len(project_only) < min_p:
        projects_pool = [a for a in catalog if a.kind == "project"]
        priority = PROJECT_PRIORITY.get(role_family, PROJECT_PRIORITY["product"])
        pool_sorted: list[Achievement] = []
        seen: set[str] = set()
        for pid in priority:
            for a in projects_pool:
                if a.parentId == pid and a.id not in seen:
                    pool_sorted.append(a)
                    seen.add(a.id)
        for a in projects_pool:
            if a.id not in seen:
                pool_sorted.append(a)
                seen.add(a.id)
        for a in pool_sorted:
            if a in selected:
                continue
            if len(work_only) > 4 and len(selected) >= max_bullets:
                # drop lowest work
                drop = work_only[-1]
                if drop in selected:
                    selected.remove(drop)
                    work_only.pop()
            if a not in selected and len(selected) < max_bullets:
                selected.append(a)
                project_only.append(a)
            if len(project_only) >= min_p:
                break
        selected = selected[:max_bullets]

    project_ids: list[str] = []
    for a in selected:
        if a.kind == "project" and a.parentId not in project_ids:
            project_ids.append(a.parentId)

    highlight_ids: list[str] = []
    if ranking and ranking.get("highlightSourceIds"):
        for sid in ranking["highlightSourceIds"]:
            if sid in by_id and by_id[sid].kind == "work" and sid not in highlight_ids:
                highlight_ids.append(sid)
    for a in selected:
        if a.kind == "work" and a.id not in highlight_ids:
            highlight_ids.append(a.id)
        if len(highlight_ids) >= MAX_HIGHLIGHTS:
            break
    highlight_ids = highlight_ids[:MAX_HIGHLIGHTS]

    omitted = [
        str(g.get("skill") or g.get("requirement") or "").strip()
        for g in (match.get("meaningfulGaps") or [])
        if str(g.get("skill") or g.get("requirement") or "").strip()
    ][:8]
    if analysis and analysis.get("candidateGaps"):
        for g in analysis["candidateGaps"]:
            g = str(g).strip()
            if g and g not in omitted:
                omitted.append(g)
            if len(omitted) >= 8:
                break

    return TailorPayload(
        targetRole=target_role,
        summary=str(positioning or "").strip(),
        selectedAchievementIds=[a.id for a in selected],
        rewrittenAchievements=[
            RewrittenAchievement(sourceId=a.id, text=a.statement) for a in selected
        ],
        highlights=[
            RewrittenAchievement(sourceId=sid, text=by_id[sid].statement)
            for sid in highlight_ids
            if sid in by_id
        ],
        selectedSkillIds=skill_ids[:MAX_SKILLS],
        selectedProjectIds=project_ids,
        skillsGrouped=_group_skills_by_category(skills, skill_ids[:MAX_SKILLS]),
        omittedRequirements=omitted,
        sectionOrder=list(DEFAULT_SECTION_ORDER),
        professionalTitle=str(candidate.get("professionalTitle") or "").strip(),
        specialtyLine=str(candidate.get("specialtyLine") or "").strip(),
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
    analysis: dict[str, Any] | None = None,
    ranking: dict[str, Any] | None = None,
    critic_feedback: str | None = None,
    pages: int = 2,
) -> tuple[dict[str, Any], str]:
    role_family = match.get("roleFamily") or "product"
    positioning = (candidate.get("positioningSummaries") or {}).get(
        role_family
    ) or ""
    if analysis and analysis.get("positioning"):
        positioning_hint = analysis["positioning"]
    else:
        positioning_hint = positioning

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
    ][:60]

    min_project = MIN_PROJECT_BULLETS.get(pages, 4)

    # Prioritize high-ranked achievements in the prompt front-matter
    priority_block = ""
    if ranking:
        ordered = ranking.get("achievements") or []
        if ordered:
            top = sorted(
                ordered,
                key=lambda a: float(a.get("score") or 0),
                reverse=True,
            )[: max_bullets + 6]
            priority_block = f"""
Pre-ranked achievements (prefer selecting from these; may use others if needed):
{json.dumps(top, indent=2)}

Suggested skillIds (select up to ~{MAX_SKILLS}, include languages + cloud + product stack): {json.dumps((ranking.get('skillIds') or [])[:24])}
Suggested projectIds: {json.dumps((ranking.get('projectIds') or [])[:8])}
Suggested highlightSourceIds (career milestones preferred over tool lists): {json.dumps((ranking.get('highlightSourceIds') or [])[:6])}
"""

    analysis_block = ""
    if analysis:
        analysis_block = f"""
Job analysis:
Positioning headline: {analysis.get('positioning') or positioning_hint}
Interview deciders: {json.dumps(analysis.get('interviewDeciders') or [])}
ATS keywords (use only when truthful to sources): {json.dumps((analysis.get('atsKeywords') or [])[:20])}
Critical/important requirements: {json.dumps([r.get('text') for r in (analysis.get('requirements') or []) if r.get('class') in ('critical', 'important')][:12])}
Candidate gaps (omit or de-emphasize; never invent coverage): {json.dumps((analysis.get('candidateGaps') or [])[:6])}
"""

    critic_block = ""
    if critic_feedback:
        critic_block = f"""
Critic feedback from prior draft — revise selection/rewrites to address MUST FIX items.
Do not invent new facts. Keep all sourceIds valid.

{critic_feedback}
"""

    prompt = f"""Tailor a resume for this job. Select at most {max_bullets} achievements.

Candidate: {candidate.get('name')}
Role family emphasis: {role_family}
Page target: {pages}
Default positioning / targetRole: {positioning_hint}
Background positioning notes (adapt lightly, do not invent facts): {positioning}

Target job:
Title: {job.get('title')}
Company: {job.get('company')}
Match score: {match.get('score')}/100 ({match.get('recommendation')})
Strong matches: {json.dumps([m.get('requirement') for m in (match.get('strongMatches') or [])[:10]])}
Meaningful gaps: {json.dumps([g.get('skill') for g in (match.get('meaningfulGaps') or [])[:8]])}
{analysis_block}
{priority_block}
{critic_block}
Job description (truncated):
{(job.get('descriptionRaw') or '')[:3500]}

Full achievement catalog (ONLY use these ids — never invent):
{json.dumps(catalog_slim, indent=2)}

Approved skills:
{json.dumps(skills_slim, indent=2)}

Selection rules:
- Include at least {min_project} project-kind achievements when the catalog has them (dual CapOne + independent profile).
- Select up to ~{MAX_SKILLS} skill ids: bias for role relevance but do NOT drop product languages (TypeScript, Swift, etc.) if approved.
- professionalTitle: short positioning headline (e.g. Principal Software Engineer) — not a fabricated job title change.
- specialtyLine: short " • "-joined themes only from real skill/role-family tokens.
- summary: 50–90 words — seniority + CapOne tenure themes + independent product work if any projects selected; at most one short promotion clause; ≤4 technology names.
- highlights: career milestones (promotions, platform span, product ownership) — NOT copies of CI/CD tool-list bullets.

Return JSON with targetRole, professionalTitle, specialtyLine, summary,
selectedAchievementIds, rewrittenAchievements (sourceId+text),
highlights (4-6 sourceId+text),
selectedSkillIds, selectedProjectIds, skillsGrouped (optional category→skillIds),
omittedRequirements, sectionOrder.
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


def _group_skills_by_category(
    skills: list[dict], skill_ids: list[str]
) -> dict[str, list[str]]:
    by_id = {s["_id"]: s for s in skills if s.get("_id")}
    grouped: dict[str, list[str]] = {}
    for sid in skill_ids:
        skill = by_id.get(sid)
        if not skill:
            continue
        cat = str(skill.get("category") or "skills").replace("_", " ").title()
        grouped.setdefault(cat, []).append(sid)
    return grouped


def _fallback_skill_ids(
    skills: list[dict], role_family: str, limit: int = MAX_SKILLS
) -> list[str]:
    if role_family == "systems":
        categories = [
            "systems",
            "iac",
            "devops",
            "cicd",
            "cloud",
            "data",
            "languages",
            "backend",
            "observability",
            "frontend",
            "mobile",
            "ai",
        ]
    elif role_family == "mobile":
        categories = ["mobile", "media", "languages", "cloud", "backend", "frontend"]
    elif role_family == "ai":
        categories = ["ai", "backend", "cloud", "languages", "frontend", "product"]
    else:
        categories = [
            "frontend",
            "product",
            "backend",
            "cloud",
            "languages",
            "auth",
            "mobile",
            "ai",
        ]

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
