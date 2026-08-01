"""Grounded application package generation (docx + pdf + markdown)."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from . import collections as C
from .db import get_db
from .matching import slugify
from .llm import generate
from .resume.achievements import build_achievement_catalog
from .resume.legacy import (
    build_resume_lines,
    build_tailored_resume_lines,
    paragraphs_to_docx,
    paragraphs_to_pdf,
)
from .resume.render_docx import render_tailored_docx
from .resume.render_rendercv import (
    build_rendercv_data,
    render_pdf_with_rendercv,
    write_rendercv_yaml,
)
from .resume.tailor import gaps_markdown, tailor_resume
from .settings import get_resume_settings

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
        work_text.append(
            f"{role.get('title')} at {role.get('company')} "
            f"({role.get('startDate')}–{role.get('endDate')})"
        )
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
        result = generate(
            prompt,
            system=COVER_SYSTEM,
            temperature=0.3,
            process="coverLetter",
        )
        return result.text.strip()
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


def _render_resume_artifacts(
    *,
    out_dir: Path,
    candidate: dict,
    work_history: list[dict],
    projects: list[dict],
    skills: list[dict],
    match: dict,
    job: dict,
    catalog,
    payload,
    resume_settings: dict,
) -> tuple[str, str, list[str]]:
    """Write resume.pdf/docx/txt/yaml. Returns (resume_text, renderer_used, extra_files)."""
    engine = (resume_settings.get("renderEngine") or "legacy").strip().lower()
    template_id = resume_settings.get("templateId") or "classic"
    extra_files: list[str] = []
    renderer_used = "legacy"

    rendercv_data = build_rendercv_data(
        candidate=candidate,
        skills=skills,
        work_history=work_history,
        projects=projects,
        catalog=catalog,
        payload=payload,
        template_id=template_id,
    )
    yaml_path = out_dir / "resume.yaml"
    write_rendercv_yaml(rendercv_data, yaml_path)
    extra_files.append("resume.yaml")

    # Structured DOCX from tailor payload (both engines)
    render_tailored_docx(
        out_dir / "resume.docx",
        candidate=candidate,
        skills=skills,
        work_history=work_history,
        projects=projects,
        catalog=catalog,
        payload=payload,
        job=job,
    )

    if payload.selectedAchievementIds:
        resume_text_lines = build_tailored_resume_lines(
            candidate=candidate,
            skills=skills,
            work_history=work_history,
            projects=projects,
            catalog=catalog,
            payload=payload,
            job=job,
        )
    else:
        resume_text_lines = build_resume_lines(
            candidate, work_history, projects, skills, match, job
        )
    resume_text = "\n".join(resume_text_lines)
    (out_dir / "resume.txt").write_text(resume_text, encoding="utf-8")

    pdf_ok = False
    if engine == "rendercv":
        try:
            render_pdf_with_rendercv(yaml_path, out_dir / "resume.pdf")
            renderer_used = "rendercv"
            pdf_ok = True
        except Exception as exc:
            logger.warning("RenderCV PDF failed, falling back to legacy: %s", exc)

    if not pdf_ok:
        paragraphs_to_pdf(out_dir / "resume.pdf", resume_text_lines)
        renderer_used = "legacy" if engine != "rendercv" else "legacy_fallback"

    return resume_text, renderer_used, extra_files


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
    resume_settings = get_resume_settings()
    pages = resume_settings.get("pages") or 2
    if pages not in (1, 2):
        pages = 2

    evidence_ids = set()
    for m in match.get("strongMatches") or []:
        evidence_ids.update(m.get("evidenceIds") or [])
    evidence_used = list(db[C.EVIDENCE].find({"_id": {"$in": list(evidence_ids)}}))
    if not evidence_used:
        evidence_used = list(
            db[C.EVIDENCE]
            .find({"candidateId": "primary-candidate", "approvedForResume": True})
            .limit(12)
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

    catalog = build_achievement_catalog(work_history, projects, skills=skills)
    payload = tailor_resume(
        candidate=candidate,
        job=job,
        match=match,
        catalog=catalog,
        skills=skills,
        pages=pages,  # type: ignore[arg-type]
    )

    selection_report = payload.to_report()
    selection_report["rendererRequested"] = resume_settings.get("renderEngine")
    selection_report["templateId"] = resume_settings.get("templateId")
    selection_report["pages"] = pages
    (out_dir / "selection-report.json").write_text(
        json.dumps(selection_report, indent=2, default=str), encoding="utf-8"
    )
    gaps_md = gaps_markdown(match, payload)
    (out_dir / "gaps.md").write_text(gaps_md, encoding="utf-8")

    resume_text, renderer_used, extra_resume_files = _render_resume_artifacts(
        out_dir=out_dir,
        candidate=candidate,
        work_history=work_history,
        projects=projects,
        skills=skills,
        match=match,
        job=job,
        catalog=catalog,
        payload=payload,
        resume_settings=resume_settings,
    )
    selection_report["renderer"] = renderer_used
    (out_dir / "selection-report.json").write_text(
        json.dumps(selection_report, indent=2, default=str), encoding="utf-8"
    )

    cover = _build_cover_letter(
        candidate, work_history, projects, match, job, evidence_used
    )
    cover_lines = cover.splitlines() or [cover]
    paragraphs_to_docx(out_dir / "cover-letter.docx", cover_lines)
    paragraphs_to_pdf(out_dir / "cover-letter.pdf", cover_lines)

    answers = _application_answers(candidate, job, match, evidence_used)
    (out_dir / "application-answers.md").write_text(answers, encoding="utf-8")
    (out_dir / "cover-letter.txt").write_text(cover, encoding="utf-8")

    package_id = f"pkg_{folder_name}"
    files = [
        "source-job.json",
        "job-description.md",
        "match-analysis.json",
        "resume.txt",
        "resume.docx",
        "resume.pdf",
        "resume.yaml",
        "selection-report.json",
        "gaps.md",
        "cover-letter.txt",
        "cover-letter.docx",
        "cover-letter.pdf",
        "application-answers.md",
        "evidence.json",
    ]
    for fname in extra_resume_files:
        if fname not in files:
            files.append(fname)

    previews = {
        "resume": {
            "title": "Resume",
            "filename": "resume.txt",
            "content": resume_text,
        },
        "selectionReport": {
            "title": "Selection report",
            "filename": "selection-report.json",
            "content": json.dumps(selection_report, indent=2, default=str),
        },
        "gaps": {
            "title": "Gaps",
            "filename": "gaps.md",
            "content": gaps_md,
        },
        "coverLetter": {
            "title": "Cover letter",
            "filename": "cover-letter.txt",
            "content": cover,
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
            {"label": "Resume YAML", "filename": "resume.yaml"},
            {"label": "Selection report", "filename": "selection-report.json"},
            {"label": "Gaps", "filename": "gaps.md"},
            {"label": "Cover letter PDF", "filename": "cover-letter.pdf"},
            {"label": "Cover letter DOCX", "filename": "cover-letter.docx"},
            {"label": "Application answers", "filename": "application-answers.md"},
        ],
        "evidenceIds": [e["_id"] for e in evidence_used],
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "roleFamily": match.get("roleFamily"),
        "renderer": renderer_used,
        "templateId": resume_settings.get("templateId"),
        "tailorPayload": {
            "targetRole": payload.targetRole,
            "selectedAchievementIds": payload.selectedAchievementIds,
            "selectedSkillIds": payload.selectedSkillIds,
            "selectedProjectIds": payload.selectedProjectIds,
            "omittedRequirements": payload.omittedRequirements,
            "usedLlm": payload.usedLlm,
            "fallbackReason": payload.fallbackReason,
            "bulletCount": len(payload.selectedAchievementIds),
        },
        "selectionSummary": {
            "bulletCount": len(payload.selectedAchievementIds),
            "omittedRequirements": payload.omittedRequirements,
            "usedLlm": payload.usedLlm,
            "renderer": renderer_used,
        },
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
                "renderer": renderer_used if fname.startswith("resume") else None,
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
    evidence_block = "\n".join(
        f"- [{e['_id']}] {e.get('claim')}" for e in evidence_used[:10]
    )
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
