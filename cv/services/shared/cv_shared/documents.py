"""Grounded application package generation (docx + pdf + markdown)."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from docx import Document
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from . import collections as C
from .db import get_db
from .matching import slugify
from .ollama_client import chat

logger = logging.getLogger(__name__)

COVER_SYSTEM = """You write a concise professional cover letter.
Use ONLY facts supplied in the evidence and work history.
Never invent employers, skills, tools, or outcomes.
Return plain text only (no markdown fences).
Keep to one page (~350-450 words).
"""


def _apps_dir() -> Path:
    return Path(os.environ.get("GENERATED_APPLICATIONS_DIR", "/app/generated-applications"))


def _safe_mkdir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _paragraphs_to_docx(path: Path, lines: list[str]) -> None:
    doc = Document()
    for line in lines:
        if not line.strip():
            doc.add_paragraph("")
        else:
            doc.add_paragraph(line)
    doc.save(str(path))


def _paragraphs_to_pdf(path: Path, lines: list[str]) -> None:
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


def _select_work_bullets(work_history: list[dict], role_family: str, limit: int = 8) -> list[tuple[dict, list[str]]]:
    # Prefer Capital One systems bullets for systems roles
    ordered = sorted(work_history, key=lambda w: w.get("startDate") or "", reverse=True)
    result = []
    for role in ordered:
        bullets = list(role.get("bullets") or [])
        if role_family == "systems":
            # keep infra-heavy bullets first
            bullets = bullets
        result.append((role, bullets[: max(3, limit // max(len(ordered), 1))]))
    return result


def _select_project_bullets(projects: list[dict], role_family: str) -> list[tuple[dict, list[str]]]:
    priority = {
        "systems": ["project_sway_sls", "project_videodl", "project_swayquest_web"],
        "mobile": ["project_ios_player", "project_android_player", "project_sway_pocket"],
        "ai": ["project_swayquest_web", "project_sway_sls", "project_sway_pocket"],
        "product": ["project_swayquest_web", "project_sway_pocket", "project_sway_sls"],
    }.get(role_family, ["project_swayquest_web", "project_sway_sls", "project_ios_player"])

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


def _skills_line(skills: list[dict], categories: list[str], limit: int = 12) -> str:
    names = []
    for skill in skills:
        if skill.get("category") in categories and skill.get("approvedForResume"):
            names.append(skill["name"])
        if len(names) >= limit:
            break
    # fallback: top approved
    if len(names) < 6:
        for skill in skills:
            if skill.get("approvedForResume") and skill["name"] not in names:
                names.append(skill["name"])
            if len(names) >= limit:
                break
    return ", ".join(names)


def _build_resume_lines(
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
            + _skills_line(skills, ["systems", "iac", "devops", "cicd", "cloud"], 14)
        )
        lines.append(
            "Data & Observability: "
            + _skills_line(skills, ["data", "observability", "databases"], 10)
        )
        lines.append("Programming: " + _skills_line(skills, ["languages", "backend"], 10))
    elif role_family == "mobile":
        lines.append("Mobile: " + _skills_line(skills, ["mobile", "media"], 12))
        lines.append("Languages: " + _skills_line(skills, ["languages"], 8))
        lines.append("Backend/Cloud: " + _skills_line(skills, ["cloud", "backend", "databases"], 10))
    else:
        lines.append("Frontend/Product: " + _skills_line(skills, ["frontend", "product", "auth", "payments"], 12))
        lines.append("Backend/Cloud: " + _skills_line(skills, ["backend", "cloud", "databases", "devops"], 12))
        lines.append("Languages: " + _skills_line(skills, ["languages", "mobile", "ai"], 10))

    lines += ["", "PROFESSIONAL EXPERIENCE"]
    for role, bullets in _select_work_bullets(work_history, role_family):
        header = f"{role.get('company')} — {role.get('companyLocation') or ''}".strip(" —")
        lines.append(header)
        lines.append(
            f"{role.get('title')} | {role.get('startDate')} – {role.get('endDate') or 'Present'}"
        )
        for b in bullets:
            lines.append(f"• {b}")
        lines.append("")

    lines.append("INDEPENDENT SYSTEMS AND PRODUCT ENGINEERING")
    lines.append("Founder & Software Engineer | Oakland, California | November 2025 – Present")
    for project, bullets in _select_project_bullets(projects, role_family):
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


def _build_cover_letter(
    candidate: dict,
    work_history: list[dict],
    projects: list[dict],
    match: dict,
    job: dict,
    evidence_used: list[dict],
) -> str:
    role_family = match.get("roleFamily") or "product"
    evidence_text = "\n".join(f"- {e.get('claim')}" for e in evidence_used[:12])
    work_text = []
    for role in work_history:
        work_text.append(f"{role.get('title')} at {role.get('company')} ({role.get('startDate')}–{role.get('endDate')})")
        for b in (role.get("bullets") or [])[:4]:
            work_text.append(f"  • {b}")

    prompt = f"""Write a cover letter for this role.

Candidate: {candidate.get('name')}, {candidate.get('location')}
Email: {candidate.get('email')}
Role family emphasis: {role_family}

Target job:
Title: {job.get('title')}
Company: {job.get('company')}
Location: {job.get('location')}
Summary of match score: {match.get('score')}/100 ({match.get('recommendation')})
Strong matches: {json.dumps([m.get('requirement') for m in (match.get('strongMatches') or [])[:8]])}
Meaningful gaps (acknowledge honestly if relevant, do not invent solutions): {json.dumps([g.get('skill') for g in (match.get('meaningfulGaps') or [])[:5]])}

Approved evidence claims only:
{evidence_text}

Work history facts:
{chr(10).join(work_text[:40])}

Independent projects (names only + given bullets already in evidence):
{chr(10).join(f"- {p.get('name')}: {p.get('summary')}" for p in projects[:5])}

Today's date: {datetime.now(timezone.utc).strftime('%B %d, %Y')}
Sign as {candidate.get('name')}.
"""
    try:
        return chat(
            prompt,
            system=COVER_SYSTEM,
            temperature=0.3,
            think_process="coverLetter",
        ).strip()
    except Exception as exc:
        logger.warning("Cover letter LLM failed, using template: %s", exc)
        return _fallback_cover(candidate, job, match, evidence_used)


def _fallback_cover(candidate: dict, job: dict, match: dict, evidence_used: list[dict]) -> str:
    claims = "\n".join(f"• {e.get('claim')}" for e in evidence_used[:6])
    return f"""{candidate.get('name')}
{candidate.get('location')} | {candidate.get('email')}

{datetime.now(timezone.utc).strftime('%B %d, %Y')}

Dear Hiring Team,

I am applying for the {job.get('title')} position at {job.get('company')}. My background includes enterprise engineering at Capital One and independent product and systems work spanning cloud infrastructure, APIs, and cross-platform applications.

Relevant evidence from my experience:
{claims}

Match assessment for this role: {match.get('score')}/100 ({match.get('recommendation')}).

Thank you for your consideration.

Sincerely,
{candidate.get('name')}
"""


def generate_application_package(job_id: str) -> dict:
    db = get_db()
    job = db[C.JOBS].find_one({"_id": job_id})
    if not job:
        raise KeyError(f"job not found: {job_id}")
    match = db[C.JOB_MATCHES].find_one({"jobId": job_id})
    if not match:
        raise RuntimeError("Analyze the job before generating documents")

    candidate = db[C.CANDIDATES].find_one({"_id": "primary-candidate"}) or {}
    work_history = list(
        db[C.WORK_HISTORY].find({"candidateId": "primary-candidate"}).sort("startDate", 1)
    )
    projects = list(db[C.PROJECTS].find({"candidateId": "primary-candidate"}))
    skills = list(db[C.SKILLS].find({"candidateId": "primary-candidate"}))

    evidence_ids = set()
    for m in match.get("strongMatches") or []:
        evidence_ids.update(m.get("evidenceIds") or [])
    evidence_used = list(db[C.EVIDENCE].find({"_id": {"$in": list(evidence_ids)}}))
    if not evidence_used:
        evidence_used = list(
            db[C.EVIDENCE].find({"candidateId": "primary-candidate", "approvedForResume": True}).limit(
                12
            )
        )

    folder_name = f"{slugify(job.get('company'))}-{slugify(job.get('title'))}"
    out_dir = _safe_mkdir(_apps_dir() / folder_name)

    # Source artifacts
    (out_dir / "source-job.json").write_text(
        json.dumps(job, indent=2, default=str), encoding="utf-8"
    )
    (out_dir / "job-description.md").write_text(
        f"# {job.get('title')} — {job.get('company')}\n\n"
        f"URL: {job.get('url') or '(none)'}\n\n"
        f"{job.get('descriptionRaw') or ''}\n",
        encoding="utf-8",
    )
    (out_dir / "match-analysis.json").write_text(
        json.dumps(match, indent=2, default=str), encoding="utf-8"
    )
    (out_dir / "evidence.json").write_text(
        json.dumps(evidence_used, indent=2, default=str), encoding="utf-8"
    )

    resume_lines = _build_resume_lines(
        candidate, work_history, projects, skills, match, job
    )
    _paragraphs_to_docx(out_dir / "resume.docx", resume_lines)
    _paragraphs_to_pdf(out_dir / "resume.pdf", resume_lines)

    cover = _build_cover_letter(
        candidate, work_history, projects, match, job, evidence_used
    )
    cover_lines = cover.splitlines() or [cover]
    _paragraphs_to_docx(out_dir / "cover-letter.docx", cover_lines)
    _paragraphs_to_pdf(out_dir / "cover-letter.pdf", cover_lines)

    answers = _application_answers(candidate, job, match, evidence_used)
    (out_dir / "application-answers.md").write_text(answers, encoding="utf-8")

    resume_text = "\n".join(resume_lines)
    cover_text = cover
    (out_dir / "resume.txt").write_text(resume_text, encoding="utf-8")
    (out_dir / "cover-letter.txt").write_text(cover_text, encoding="utf-8")

    package_id = f"pkg_{folder_name}"
    files = [
        "source-job.json",
        "job-description.md",
        "match-analysis.json",
        "resume.txt",
        "resume.docx",
        "resume.pdf",
        "cover-letter.txt",
        "cover-letter.docx",
        "cover-letter.pdf",
        "application-answers.md",
        "evidence.json",
    ]
    previews = {
        "resume": {
            "title": "Resume",
            "filename": "resume.txt",
            "content": resume_text,
        },
        "coverLetter": {
            "title": "Cover letter",
            "filename": "cover-letter.txt",
            "content": cover_text,
        },
        "applicationAnswers": {
            "title": "Application answers",
            "filename": "application-answers.md",
            "content": answers,
        },
        "matchAnalysis": {
            "title": "Match analysis",
            "filename": "match-analysis.json",
            "content": json.dumps(match, indent=2, default=str),
        },
        "evidence": {
            "title": "Evidence used",
            "filename": "evidence.json",
            "content": json.dumps(evidence_used, indent=2, default=str),
        },
    }
    package = {
        "_id": package_id,
        "jobId": job_id,
        "candidateId": "primary-candidate",
        "folder": str(out_dir),
        "folderName": folder_name,
        "files": files,
        "previews": previews,
        "downloads": [
            {"label": "Resume PDF", "filename": "resume.pdf"},
            {"label": "Resume DOCX", "filename": "resume.docx"},
            {"label": "Cover letter PDF", "filename": "cover-letter.pdf"},
            {"label": "Cover letter DOCX", "filename": "cover-letter.docx"},
            {"label": "Application answers", "filename": "application-answers.md"},
        ],
        "evidenceIds": [e["_id"] for e in evidence_used],
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "roleFamily": match.get("roleFamily"),
    }
    db[C.APPLICATION_PACKAGES].replace_one({"_id": package_id}, package, upsert=True)

    app_doc = {
        "_id": f"app_{job_id}",
        "jobId": job_id,
        "packageId": package_id,
        "status": "drafted",
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    db[C.APPLICATIONS].replace_one({"_id": app_doc["_id"]}, app_doc, upsert=True)
    db[C.JOBS].update_one({"_id": job_id}, {"$set": {"status": "drafted"}})

    for fname in package["files"]:
        db[C.DOCUMENTS].replace_one(
            {"_id": f"doc_{package_id}_{fname}"},
            {
                "_id": f"doc_{package_id}_{fname}",
                "packageId": package_id,
                "jobId": job_id,
                "filename": fname,
                "path": str(out_dir / fname),
            },
            upsert=True,
        )

    return package


def _application_answers(
    candidate: dict, job: dict, match: dict, evidence_used: list[dict]
) -> str:
    why = (
        f"I am interested in {job.get('company')} because the role ({job.get('title')}) "
        f"aligns with my experience in {(match.get('roleFamily') or 'product')} engineering. "
        f"Verified strengths include: "
        + ", ".join(m.get("requirement") for m in (match.get("strongMatches") or [])[:5])
        + "."
    )
    gaps = match.get("meaningfulGaps") or []
    gap_block = (
        "\n".join(f"- {g.get('skill')}: {g.get('reason')}" for g in gaps[:5])
        if gaps
        else "- None flagged as critical."
    )
    evidence_block = "\n".join(f"- [{e['_id']}] {e.get('claim')}" for e in evidence_used[:10])
    return f"""# Application answers — {job.get('title')} @ {job.get('company')}

## Why do you want to work here?
{why}

## Qualification summary
Match score: **{match.get('score')}/100** ({match.get('recommendation')})

### Strong evidence
{chr(10).join(f"- {m.get('requirement')}" for m in (match.get('strongMatches') or [])[:10]) or '- (none)'}

### Meaningful gaps
{gap_block}

### Why still viable
{match.get('whyViable') or 'N/A'}

## Portfolio / evidence to attach
{evidence_block}

## Missing-information checklist
- [ ] Confirm work authorization / location requirements
- [ ] Confirm salary range vs minimum (${candidate.get('minimumSalary')})
- [ ] Review generated resume and cover letter before submit
- [ ] Open application URL and submit manually (Level 1)

## Recruiter message (short)
Hi — I'm {candidate.get('name')}, applying for {job.get('title')}. Happy to share a tailored resume emphasizing my most relevant {(match.get('roleFamily') or 'product')} experience.
"""
