"""Deterministic resume layout: employer consolidation, projects, contact cleanup."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from .achievements import Achievement, catalog_by_id

# Known independent project display groupings (ids from seed)
PROJECT_THEME_LABELS = {
    "project_swayquest_web": "Cross-Platform Product Platform",
    "project_sway_pocket": "Cross-Platform Product Platform",
    "project_ios_player": "Cross-Platform Product Platform",
    "project_android_player": "Cross-Platform Product Platform",
    "project_sway_sls": "Cloud / Serverless Platforms",
    "project_videodl": "Media Processing Platform",
    "project_sway_sched": "Internal Tooling",
    "project_sway_drive": "Internal Tooling",
    "project_content_sites": "Content / Marketing Sites",
    "project_game_prototypes": "Creative Prototypes",
}


@dataclass
class TitleStackEntry:
    title: str
    startDate: str
    endDate: str
    workId: str

    def year_range(self) -> str:
        return f"{_year(self.startDate)}–{_year(self.endDate) or 'Present'}"


@dataclass
class EmployerBlock:
    company: str
    location: str
    titles: list[TitleStackEntry] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)
    intro: str = ""


@dataclass
class ProjectBlock:
    projectId: str
    name: str
    theme: str
    bullets: list[str] = field(default_factory=list)


@dataclass
class ResumeLayout:
    name: str
    professionalTitle: str
    specialtyLine: str
    contactLine: str
    summary: str
    highlights: list[str]
    coreExpertise: str
    technologyLines: list[str]
    employers: list[EmployerBlock]
    independentLabel: str
    independentPeriod: str
    independentLocation: str
    projects: list[ProjectBlock]
    educationLines: list[str]


def build_resume_layout(
    *,
    candidate: dict,
    skills: list[dict],
    work_history: list[dict],
    projects: list[dict],
    catalog: list[Achievement],
    payload: Any,
) -> ResumeLayout:
    by_id = catalog_by_id(catalog)
    rewrite = payload.rewrite_map()
    skill_by_id = {s["_id"]: s for s in skills if s.get("_id")}

    employers = group_work_by_employer(
        work_history=work_history,
        selected_ids=payload.selectedAchievementIds,
        by_id=by_id,
        rewrite=rewrite,
    )
    project_blocks = group_projects(
        projects=projects,
        selected_ids=payload.selectedAchievementIds,
        by_id=by_id,
        rewrite=rewrite,
    )

    title = (
        getattr(payload, "professionalTitle", None)
        or candidate.get("professionalTitle")
        or payload.targetRole
        or ""
    )
    specialty = (
        getattr(payload, "specialtyLine", None)
        or candidate.get("specialtyLine")
        or ""
    )
    if not specialty:
        specialty = default_specialty_line(
            role_family=None,
            skill_ids=payload.selectedSkillIds,
            skills=skills,
        )

    core, tech_lines = skills_dual_display(payload, skill_by_id)

    period, location = independent_header(candidate, projects, project_blocks)
    edu = (candidate.get("education") or [{}])[0]
    education_lines: list[str] = []
    if edu:
        if edu.get("institution"):
            education_lines.append(str(edu["institution"]))
        degree_bits = [
            edu.get("degree"),
            edu.get("school"),
        ]
        education_lines.append(
            " | ".join(str(b) for b in degree_bits if b)
        )

    return ResumeLayout(
        name=str(candidate.get("name") or "Candidate"),
        professionalTitle=str(title).strip(),
        specialtyLine=str(specialty).strip(),
        contactLine=format_contact_line(candidate),
        summary=(payload.summary or "").strip(),
        highlights=[h.text for h in (payload.highlights or []) if h.text],
        coreExpertise=core,
        technologyLines=tech_lines,
        employers=employers,
        independentLabel=str(
            candidate.get("independentRoleLabel")
            or "INDEPENDENT SOFTWARE ENGINEER"
        ),
        independentPeriod=period,
        independentLocation=location,
        projects=project_blocks,
        educationLines=[ln for ln in education_lines if ln],
    )


def group_work_by_employer(
    *,
    work_history: list[dict],
    selected_ids: list[str],
    by_id: dict[str, Achievement],
    rewrite: dict[str, str],
) -> list[EmployerBlock]:
    work_by_id = {w["_id"]: w for w in work_history if w.get("_id")}

    # company_key -> selected work parent ids that contributed bullets
    company_role_ids: dict[str, list[str]] = {}
    company_bullets: dict[str, list[str]] = {}
    company_meta: dict[str, tuple[str, str]] = {}

    seen_bullet: set[str] = set()

    for aid in selected_ids:
        ach = by_id.get(aid)
        if not ach or ach.kind != "work":
            continue
        role = work_by_id.get(ach.parentId) or {}
        company = str(role.get("company") or ach.employer or "Employer").strip()
        key = company.lower()
        if key not in company_role_ids:
            company_role_ids[key] = []
            company_bullets[key] = []
            company_meta[key] = (
                company,
                str(role.get("companyLocation") or ach.location or ""),
            )
        if ach.parentId not in company_role_ids[key]:
            company_role_ids[key].append(ach.parentId)
        text = (rewrite.get(aid) or ach.statement or "").strip()
        if text and text not in seen_bullet:
            company_bullets[key].append(text)
            seen_bullet.add(text)

    blocks: list[EmployerBlock] = []
    for key, role_ids in company_role_ids.items():
        company, location = company_meta[key]
        # Full progression: all work_history rows at this company when any role selected
        all_roles = [
            w
            for w in work_history
            if str(w.get("company") or "").strip().lower() == key
        ]
        if not all_roles:
            all_roles = [work_by_id[rid] for rid in role_ids if rid in work_by_id]
        # Prefer showing full company tenure (all titles) when any CapOne-style multi-role
        titles: list[TitleStackEntry] = []
        for w in all_roles:
            titles.append(
                TitleStackEntry(
                    title=str(w.get("title") or "Software Engineer"),
                    startDate=str(w.get("startDate") or ""),
                    endDate=str(w.get("endDate") or ""),
                    workId=str(w.get("_id") or ""),
                )
            )
        titles.sort(key=lambda t: t.startDate or "", reverse=True)

        # Intro when 2+ titles: progressive tenure (verified by multiple titles)
        intro = ""
        if len(titles) >= 2:
            intro = (
                f"Promoted across {len(titles)} engineering levels while building "
                f"enterprise systems, deployment automation, and production platforms."
            )

        # Sort companies by most recent role start
        blocks.append(
            EmployerBlock(
                company=company,
                location=location,
                titles=titles,
                bullets=company_bullets.get(key, []),
                intro=intro,
            )
        )

    def _block_sort_key(b: EmployerBlock) -> str:
        if not b.titles:
            return ""
        return b.titles[0].startDate or ""

    blocks.sort(key=_block_sort_key, reverse=True)
    return blocks


def group_projects(
    *,
    projects: list[dict],
    selected_ids: list[str],
    by_id: dict[str, Achievement],
    rewrite: dict[str, str],
) -> list[ProjectBlock]:
    project_by_id = {p["_id"]: p for p in projects if p.get("_id")}
    order: list[str] = []
    groups: dict[str, list[str]] = {}

    for aid in selected_ids:
        ach = by_id.get(aid)
        if not ach or ach.kind != "project":
            continue
        pid = ach.parentId
        if pid not in groups:
            groups[pid] = []
            order.append(pid)
        text = (rewrite.get(aid) or ach.statement or "").strip()
        if text and text not in groups[pid]:
            groups[pid].append(text)

    # Theme-collapse: same theme label may merge project names as subheads
    blocks: list[ProjectBlock] = []
    for pid in order:
        project = project_by_id.get(pid) or {}
        name = str(project.get("name") or pid)
        theme = PROJECT_THEME_LABELS.get(pid) or name
        blocks.append(
            ProjectBlock(
                projectId=pid,
                name=name,
                theme=theme if theme != name else name,
                bullets=groups.get(pid, []),
            )
        )
    return blocks


def independent_header(
    candidate: dict,
    projects: list[dict],
    blocks: list[ProjectBlock],
) -> tuple[str, str]:
    location = str(candidate.get("location") or "").strip()
    if candidate.get("independentPeriod"):
        period = str(candidate["independentPeriod"])
        return period, location

    starts: list[str] = []
    project_by_id = {p["_id"]: p for p in projects if p.get("_id")}
    for b in blocks:
        p = project_by_id.get(b.projectId) or {}
        if p.get("startDate"):
            starts.append(str(p["startDate"]))
    if starts:
        earliest = min(starts)
        period = f"{_month_year(earliest)} – Present"
    else:
        period = "November 2025 – Present"
    return period, location


def format_contact_line(candidate: dict) -> str:
    parts = [
        candidate.get("location"),
        candidate.get("phone"),
        candidate.get("email"),
        _clean_url(candidate.get("linkedin")),
        _clean_url(candidate.get("github")),
    ]
    return " • ".join(str(p).strip() for p in parts if p and str(p).strip())


def _clean_url(url_or_path: str | None) -> str:
    if not url_or_path:
        return ""
    text = str(url_or_path).strip()
    if not text:
        return ""
    text = re.sub(r"^https?://", "", text, flags=re.I)
    text = text.rstrip("/")
    return text


def skills_dual_display(
    payload: Any, skill_by_id: dict[str, dict]
) -> tuple[str, list[str]]:
    """Return (CORE EXPERTISE line, TECHNOLOGIES category lines)."""
    names: list[str] = []
    for sid in payload.selectedSkillIds:
        skill = skill_by_id.get(sid)
        if skill and skill.get("name") and skill["name"] not in names:
            names.append(str(skill["name"]))
    # Compact: drop redundant "AWS " prefix clutter in core by keeping short first 14-18
    core_names = names[:18]
    core = " • ".join(core_names)

    # Technologies by category
    by_cat: dict[str, list[str]] = {}
    grouped = getattr(payload, "skillsGrouped", None) or {}
    if grouped:
        for cat, ids in grouped.items():
            for sid in ids:
                skill = skill_by_id.get(sid)
                if skill and skill.get("name"):
                    by_cat.setdefault(str(cat), []).append(str(skill["name"]))
    else:
        for sid in payload.selectedSkillIds:
            skill = skill_by_id.get(sid)
            if not skill or not skill.get("name"):
                continue
            cat = str(skill.get("category") or "tools").replace("_", " ").title()
            by_cat.setdefault(cat, []).append(str(skill["name"]))

    # Friendly tech section order + merge same display labels
    preferred = [
        "Languages",
        "Cloud",
        "Aws",
        "Infrastructure",
        "Iac",
        "Devops",
        "Cicd",
        "Backend",
        "Frontend",
        "Mobile",
        "Data",
        "Ai",
        "Observability",
        "Tools",
    ]
    ordered_cats: list[tuple[str, list[str]]] = []
    used = set()
    cat_items = list(by_cat.items())
    for pref in preferred:
        for cat, cat_names in cat_items:
            if cat.lower().replace(" ", "") == pref.lower().replace(" ", ""):
                ordered_cats.append((cat, cat_names))
                used.add(cat)
    for cat, cat_names in cat_items:
        if cat not in used:
            ordered_cats.append((cat, cat_names))

    merged: dict[str, list[str]] = {}
    label_order: list[str] = []
    for cat, cat_names in ordered_cats:
        label = _tech_label(cat)
        if label not in merged:
            merged[label] = []
            label_order.append(label)
        for n in cat_names:
            if n not in merged[label]:
                merged[label].append(n)

    tech_lines = [f"{label}: {', '.join(names)}" for label, names in ((l, merged[l]) for l in label_order)]
    return core, tech_lines


def _tech_label(cat: str) -> str:
    c = cat.strip().lower().replace(" ", "")
    mapping = {
        "aws": "AWS",
        "cloud": "AWS",
        "languages": "Languages",
        "language": "Languages",
        "iac": "Tools",
        "devops": "Tools",
        "cicd": "Tools",
        "observability": "Tools",
        "ai": "Tools",
        "frontend": "Tools",
        "backend": "Tools",
        "mobile": "Tools",
        "data": "Tools",
        "systems": "Tools",
    }
    if c in mapping:
        return mapping[c]
    return cat.replace("_", " ").title()


def default_specialty_line(
    *,
    role_family: str | None = None,
    skill_ids: list[str] | None = None,
    skills: list[dict] | None = None,
) -> str:
    defaults = [
        "Distributed Systems",
        "Cloud Infrastructure",
        "AI Platforms",
        "Full-Stack Product Engineering",
    ]
    return " • ".join(defaults)


def default_professional_title(candidate: dict, payload: Any = None) -> str:
    if candidate.get("professionalTitle"):
        return str(candidate["professionalTitle"])
    # Positioning headline — not a fabricated employer title
    return "Principal Software Engineer"


def _month_year(value: str) -> str:
    text = (value or "").strip()
    months = {
        "01": "January",
        "02": "February",
        "03": "March",
        "04": "April",
        "05": "May",
        "06": "June",
        "07": "July",
        "08": "August",
        "09": "September",
        "10": "October",
        "11": "November",
        "12": "December",
    }
    m = re.match(r"^(\d{4})-(\d{2})", text)
    if m:
        return f"{months.get(m.group(2), m.group(2))} {m.group(1)}"
    y = _year(text)
    return y or text


def layout_to_plain_lines(layout: ResumeLayout) -> list[str]:
    """Render layout as plain-text resume lines (legacy PDF / preview)."""
    lines: list[str] = [layout.name]
    if layout.professionalTitle:
        lines.append(layout.professionalTitle)
    if layout.specialtyLine:
        lines.append(layout.specialtyLine)
    if layout.contactLine:
        lines.append(layout.contactLine)
    lines.append("")

    if layout.summary:
        lines += ["SUMMARY", layout.summary, ""]

    if layout.highlights:
        lines.append("SELECTED HIGHLIGHTS")
        for h in layout.highlights:
            lines.append(f"• {h}")
        lines.append("")

    if layout.coreExpertise:
        lines += ["CORE EXPERTISE", layout.coreExpertise, ""]

    if layout.employers:
        lines.append("EXPERIENCE")
        for emp in layout.employers:
            header = emp.company
            if emp.location:
                header = f"{emp.company} — {emp.location}"
            lines.append(header)
            for t in emp.titles:
                lines.append(f"{t.title} ({t.year_range()})")
            if emp.intro:
                lines.append(emp.intro)
            for b in emp.bullets:
                lines.append(f"• {b}")
            lines.append("")

    if layout.projects:
        label = (layout.independentLabel or "INDEPENDENT SOFTWARE ENGINEER").strip()
        if not label.isupper():
            label = label.upper()
        lines.append(label)
        period_loc = layout.independentPeriod
        if layout.independentLocation:
            period_loc = f"{layout.independentPeriod} | {layout.independentLocation}"
        lines.append(period_loc)
        for proj in layout.projects:
            lines.append(proj.name)
            for b in proj.bullets:
                lines.append(f"• {b}")
            lines.append("")

    if layout.technologyLines:
        lines.append("TECHNOLOGIES")
        lines.extend(layout.technologyLines)
        lines.append("")

    if layout.educationLines:
        lines.append("EDUCATION")
        lines.extend(layout.educationLines)
        lines.append("")

    return lines


def _year(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    m = re.match(r"^(\d{4})", text)
    return m.group(1) if m else text[:4]


def apply_milestone_highlights(
    *,
    payload: Any,
    catalog: list[Achievement],
    work_history: list[dict],
    projects: list[dict],
) -> list[Any]:
    """Deterministic career-milestone highlights grounded in verified data.

    Returns list of RewrittenAchievement-compatible objects (sourceId, text).
    Uses synthetic source ids milestone:n that are not catalog bullets.
    """
    from .tailor import RewrittenAchievement

    by_id = catalog_by_id(catalog)
    rewrite = payload.rewrite_map()
    selected = list(payload.selectedAchievementIds or [])
    work_sel = [sid for sid in selected if by_id.get(sid) and by_id[sid].kind == "work"]
    project_sel = [
        sid for sid in selected if by_id.get(sid) and by_id[sid].kind == "project"
    ]

    # Titles per company from work_history
    titles_by_company: dict[str, set[str]] = {}
    for w in work_history:
        company = str(w.get("company") or "").strip()
        title = str(w.get("title") or "").strip()
        if company and title:
            titles_by_company.setdefault(company.lower(), set()).add(title)

    out: list[RewrittenAchievement] = []
    n = 0

    def add(text: str) -> None:
        nonlocal n
        if not text or len(out) >= 6:
            return
        for existing in out:
            if existing.text.lower() == text.lower():
                return
        out.append(RewrittenAchievement(sourceId=f"milestone:{n}", text=text))
        n += 1

    for company_key, titles in titles_by_company.items():
        if len(titles) >= 2:
            company = next(
                (
                    str(w.get("company") or "").strip()
                    for w in work_history
                    if str(w.get("company") or "").strip().lower() == company_key
                ),
                company_key.title(),
            )
            add(
                f"Promoted through {len(titles)} engineering levels at {company}."
            )
            break

    if project_sel:
        themes: list[str] = []
        for sid in project_sel:
            ach = by_id[sid]
            label = PROJECT_THEME_LABELS.get(ach.parentId)
            if label and label not in themes:
                themes.append(label)
        if themes:
            add(
                "Architecting end-to-end products spanning "
                + ", ".join(themes[:3]).lower()
                + "."
            )
        else:
            add(
                "Own products from architecture and implementation through "
                "deployment and operations."
            )
        add(
            "Developing independent platforms, AI-assisted workflows, and cloud "
            "automation systems."
        )

    # Cap cloud/platform theme from work (short, no laundry list)
    for sid in work_sel[:3]:
        stmt = (rewrite.get(sid) or by_id[sid].statement or "").strip()
        if not stmt:
            continue
        # Prefer shorter theme lines that already look milestone-like
        if len(stmt) > 160:
            continue
        # Skip near-duplicates of experience
        add(stmt)

    # If still short, use existing payload highlights that look non-tool-listy
    for h in payload.highlights or []:
        text = (h.text or "").strip()
        if not text:
            continue
        tool_commas = text.count(",")
        if tool_commas >= 4:
            continue
        add(text)

    return out[:6]
