"""Derive addressable achievement units from work history and projects."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Achievement:
    id: str
    kind: str  # work | project
    statement: str
    parentId: str
    employer: str = ""
    role: str = ""
    title: str = ""
    startDate: str = ""
    endDate: str = ""
    location: str = ""
    skillIds: list[str] = field(default_factory=list)
    evidenceIds: list[str] = field(default_factory=list)
    approvedForResume: bool = True
    categories: list[str] = field(default_factory=list)
    allowedRewrites: list[str] = field(
        default_factory=lambda: [
            "shorten",
            "emphasizeRelevantSkills",
            "actionResult",
        ]
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def work_achievement_id(work_id: str, index: int) -> str:
    return f"work:{work_id}:b{index}"


def project_achievement_id(project_id: str, index: int) -> str:
    return f"project:{project_id}:b{index}"


def build_achievement_catalog(
    work_history: list[dict],
    projects: list[dict],
    *,
    skills: list[dict] | None = None,
) -> list[Achievement]:
    """Build catalog from work bullets and project resumeBullets.

    Work bullets inherit approval from parent (always treated as approved when
    present on seeded work history). Project bullets are approved when present.
    Skills map is optional and used only to attach category tags.
    """
    skill_by_id = {s["_id"]: s for s in (skills or []) if s.get("_id")}
    catalog: list[Achievement] = []

    for role in work_history or []:
        work_id = str(role.get("_id") or "")
        if not work_id:
            continue
        skill_ids = list(role.get("skillIds") or [])
        evidence_ids = list(role.get("evidenceIds") or [])
        categories = _categories_for_skills(skill_ids, skill_by_id)
        for i, bullet in enumerate(role.get("bullets") or []):
            text = (bullet or "").strip()
            if not text:
                continue
            catalog.append(
                Achievement(
                    id=work_achievement_id(work_id, i),
                    kind="work",
                    statement=text,
                    parentId=work_id,
                    employer=str(role.get("company") or ""),
                    role=str(role.get("title") or ""),
                    title=str(role.get("title") or ""),
                    startDate=str(role.get("startDate") or ""),
                    endDate=str(role.get("endDate") or ""),
                    location=str(role.get("companyLocation") or ""),
                    skillIds=skill_ids,
                    evidenceIds=evidence_ids,
                    approvedForResume=True,
                    categories=categories,
                )
            )

    for project in projects or []:
        project_id = str(project.get("_id") or "")
        if not project_id:
            continue
        skill_ids = list(project.get("skillIds") or [])
        evidence_ids = list(project.get("evidenceIds") or [])
        categories = _categories_for_skills(skill_ids, skill_by_id)
        bullets = list(project.get("resumeBullets") or [])
        if not bullets and project.get("summary"):
            bullets = [str(project["summary"])]
        for i, bullet in enumerate(bullets):
            text = (bullet or "").strip()
            if not text:
                continue
            catalog.append(
                Achievement(
                    id=project_achievement_id(project_id, i),
                    kind="project",
                    statement=text,
                    parentId=project_id,
                    employer="Independent",
                    role="Founder & Software Engineer",
                    title=str(project.get("name") or "Project"),
                    startDate=str(project.get("startDate") or ""),
                    endDate=str(project.get("endDate") or ""),
                    location="",
                    skillIds=skill_ids,
                    evidenceIds=evidence_ids,
                    approvedForResume=True,
                    categories=categories,
                )
            )

    return catalog


def catalog_by_id(catalog: list[Achievement]) -> dict[str, Achievement]:
    return {a.id: a for a in catalog}


def _categories_for_skills(
    skill_ids: list[str], skill_by_id: dict[str, dict]
) -> list[str]:
    cats: list[str] = []
    seen: set[str] = set()
    for sid in skill_ids:
        skill = skill_by_id.get(sid) or {}
        cat = (skill.get("category") or "").strip()
        if cat and cat not in seen:
            seen.add(cat)
            cats.append(cat)
    return cats
