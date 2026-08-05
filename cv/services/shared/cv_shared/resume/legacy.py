"""Legacy plain-text resume builder (ReportLab / line dump)."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from .tailor import PROJECT_PRIORITY


def select_work_bullets(
    work_history: list[dict], role_family: str, limit: int = 8
) -> list[tuple[dict, list[str]]]:
    ordered = sorted(work_history, key=lambda w: w.get("startDate") or "", reverse=True)
    result = []
    for role in ordered:
        bullets = list(role.get("bullets") or [])
        result.append((role, bullets[: max(3, limit // max(len(ordered), 1))]))
    return result


def select_project_bullets(
    projects: list[dict], role_family: str
) -> list[tuple[dict, list[str]]]:
    priority = PROJECT_PRIORITY.get(
        role_family, PROJECT_PRIORITY["product"]
    )
    by_id = {p["_id"]: p for p in projects}
    selected = []
    for pid in priority:
        if pid in by_id:
            selected.append(by_id[pid])
    for p in projects:
        if p not in selected:
            selected.append(p)
        if len(selected) >= 4:
            break
    return [(p, list(p.get("resumeBullets") or [])[:3]) for p in selected]


def skills_line(skills: list[dict], categories: list[str], limit: int = 12) -> str:
    names = []
    for skill in skills:
        if skill.get("category") in categories and skill.get("approvedForResume"):
            names.append(skill["name"])
        if len(names) >= limit:
            break
    if len(names) < 6:
        for skill in skills:
            if skill.get("approvedForResume") and skill["name"] not in names:
                names.append(skill["name"])
            if len(names) >= limit:
                break
    return ", ".join(names)


def build_resume_lines(
    candidate: dict,
    work_history: list[dict],
    projects: list[dict],
    skills: list[dict],
    match: dict,
    job: dict,
) -> list[str]:
    role_family = match.get("roleFamily") or "product"
    positioning = (candidate.get("positioningSummaries") or {}).get(
        role_family
    ) or (candidate.get("positioningSummaries") or {}).get("product", "")

    contact = " | ".join(
        filter(
            None,
            [
                candidate.get("location"),
                candidate.get("email"),
                candidate.get("phone"),
                candidate.get("linkedin"),
                candidate.get("github"),
            ],
        )
    )

    lines = [
        candidate.get("name") or "Candidate",
        contact,
        "",
        "PROFESSIONAL SUMMARY",
        positioning,
        "",
        "TECHNICAL SKILLS",
    ]

    if role_family == "systems":
        lines.append(
            "Systems & Infrastructure: "
            + skills_line(skills, ["systems", "iac", "devops", "cicd", "cloud"], 14)
        )
        lines.append(
            "Data & Observability: "
            + skills_line(skills, ["data", "observability", "databases"], 10)
        )
        lines.append("Programming: " + skills_line(skills, ["languages", "backend"], 10))
    elif role_family == "mobile":
        lines.append("Mobile: " + skills_line(skills, ["mobile", "media"], 12))
        lines.append("Languages: " + skills_line(skills, ["languages"], 8))
        lines.append(
            "Backend/Cloud: " + skills_line(skills, ["cloud", "backend", "databases"], 10)
        )
    else:
        lines.append(
            "Frontend/Product: "
            + skills_line(skills, ["frontend", "product", "auth", "payments"], 12)
        )
        lines.append(
            "Backend/Cloud: "
            + skills_line(skills, ["backend", "cloud", "databases", "devops"], 12)
        )
        lines.append(
            "Languages: " + skills_line(skills, ["languages", "mobile", "ai"], 10)
        )

    lines += ["", "PROFESSIONAL EXPERIENCE"]
    for role, bullets in select_work_bullets(work_history, role_family):
        header = f"{role.get('company')} — {role.get('companyLocation') or ''}".strip(
            " —"
        )
        lines.append(header)
        lines.append(
            f"{role.get('title')} | {role.get('startDate')} – {role.get('endDate') or 'Present'}"
        )
        for b in bullets:
            lines.append(f"• {b}")
        lines.append("")

    lines.append("INDEPENDENT SYSTEMS AND PRODUCT ENGINEERING")
    lines.append(
        "Founder & Software Engineer | Oakland, California | November 2025 – Present"
    )
    for project, bullets in select_project_bullets(projects, role_family):
        lines.append(project.get("name") or "Project")
        for b in bullets:
            lines.append(f"• {b}")
        if not bullets and project.get("summary"):
            lines.append(f"• {project['summary']}")
        lines.append("")

    edu = (candidate.get("education") or [{}])[0]
    lines += [
        "EDUCATION",
        edu.get("institution") or "",
        f"{edu.get('degree') or ''} | {edu.get('school') or ''} | {edu.get('location') or ''} | {edu.get('graduatedAt') or ''}",
        "",
        f"Tailored for: {job.get('title')} at {job.get('company')} (role family: {role_family})",
    ]
    return lines


def build_tailored_resume_lines(
    *,
    candidate: dict,
    skills: list[dict],
    work_history: list[dict],
    projects: list[dict],
    catalog: list,
    payload,
    job: dict | None = None,
) -> list[str]:
    """Plain-text resume lines from a verified TailorPayload (legacy PDF/txt)."""
    by_id = {a.id: a for a in catalog}
    rewrite = payload.rewrite_map()
    skill_by_id = {s["_id"]: s for s in skills if s.get("_id")}
    work_by_id = {w["_id"]: w for w in work_history if w.get("_id")}
    project_by_id = {p["_id"]: p for p in projects if p.get("_id")}

    contact = " | ".join(
        filter(
            None,
            [
                candidate.get("location"),
                candidate.get("email"),
                candidate.get("phone"),
                candidate.get("linkedin"),
                candidate.get("github"),
            ],
        )
    )
    lines = [candidate.get("name") or "Candidate", contact, ""]
    if getattr(payload, "targetRole", None):
        lines += [str(payload.targetRole), ""]
    if payload.summary:
        lines += ["PROFESSIONAL SUMMARY", payload.summary, ""]

    highlights = list(getattr(payload, "highlights", None) or [])
    if highlights:
        lines.append("SELECTED HIGHLIGHTS")
        for h in highlights:
            lines.append(f"• {h.text}")
        lines.append("")

    skill_lines = _format_skill_lines(payload, skill_by_id)
    if skill_lines:
        lines.append("TECHNICAL SKILLS")
        lines.extend(skill_lines)
        lines.append("")

    work_order: list[str] = []
    work_groups: dict[str, list[str]] = {}
    for aid in payload.selectedAchievementIds:
        ach = by_id.get(aid)
        if not ach or ach.kind != "work":
            continue
        if ach.parentId not in work_groups:
            work_groups[ach.parentId] = []
            work_order.append(ach.parentId)
        work_groups[ach.parentId].append(rewrite.get(aid) or ach.statement)

    if work_order:
        lines.append("PROFESSIONAL EXPERIENCE")
        for wid in work_order:
            role = work_by_id.get(wid) or {}
            lines.append(
                f"{role.get('company') or 'Employer'} — {role.get('title') or ''}".strip(
                    " —"
                )
            )
            lines.append(
                f"{role.get('startDate') or ''} – {role.get('endDate') or 'Present'}"
            )
            for b in work_groups[wid]:
                lines.append(f"• {b}")
            lines.append("")

    project_order: list[str] = []
    project_groups: dict[str, list[str]] = {}
    for aid in payload.selectedAchievementIds:
        ach = by_id.get(aid)
        if not ach or ach.kind != "project":
            continue
        if ach.parentId not in project_groups:
            project_groups[ach.parentId] = []
            project_order.append(ach.parentId)
        project_groups[ach.parentId].append(rewrite.get(aid) or ach.statement)

    if project_order:
        lines.append("INDEPENDENT PROJECTS")
        lines.append(
            "Founder & Software Engineer | Oakland, California | November 2025 – Present"
        )
        for pid in project_order:
            project = project_by_id.get(pid) or {}
            lines.append(project.get("name") or pid)
            for b in project_groups[pid]:
                lines.append(f"• {b}")
            lines.append("")

    edu = (candidate.get("education") or [{}])[0]
    if edu:
        lines.append("EDUCATION")
        if edu.get("institution"):
            lines.append(str(edu.get("institution")))
        edu_line = " | ".join(
            filter(
                None,
                [
                    edu.get("degree"),
                    edu.get("school"),
                    edu.get("location"),
                    edu.get("graduatedAt"),
                ],
            )
        )
        if edu_line:
            lines.append(edu_line)
        lines.append("")

    if job:
        lines.append(f"Tailored for: {job.get('title')} at {job.get('company')}")
    return lines


def _format_skill_lines(payload, skill_by_id: dict) -> list[str]:
    """Grouped skill lines when payload.skillsGrouped is present."""
    grouped = getattr(payload, "skillsGrouped", None) or {}
    if grouped:
        lines: list[str] = []
        for cat, ids in grouped.items():
            names = [
                skill_by_id[sid]["name"]
                for sid in ids
                if sid in skill_by_id and skill_by_id[sid].get("name")
            ]
            if names:
                lines.append(f"{cat}: {', '.join(names)}")
        if lines:
            return lines
    skill_names = [
        skill_by_id[sid]["name"]
        for sid in payload.selectedSkillIds
        if sid in skill_by_id and skill_by_id[sid].get("name")
    ]
    if skill_names:
        return [", ".join(skill_names)]
    return []


def paragraphs_to_docx(path: Path, lines: list[str]) -> None:
    doc = Document()
    for line in lines:
        if not line.strip():
            doc.add_paragraph("")
        else:
            doc.add_paragraph(line)
    doc.save(str(path))


def paragraphs_to_pdf(path: Path, lines: list[str]) -> None:
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=13,
        spaceAfter=6,
    )
    header = ParagraphStyle(
        "Header",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=18,
        spaceAfter=10,
    )
    story = []
    for i, line in enumerate(lines):
        text = (line or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if not text.strip():
            story.append(Spacer(1, 0.12 * inch))
            continue
        style = header if i == 0 else body
        story.append(Paragraph(text, style))
    pdf = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )
    pdf.build(story)
