"""Cover letter composer with shared resume evidence context."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from ..llm import generate
from ..resume.achievements import Achievement
from ..resume.tailor import TailorPayload
from .job_analyzer import JobAnalysis
from .prompts import COVER_LETTER_SYSTEM

logger = logging.getLogger(__name__)


def build_cover_letter(
    *,
    candidate: dict,
    job: dict,
    match: dict,
    analysis: JobAnalysis | None = None,
    payload: TailorPayload | None = None,
    catalog: list[Achievement] | None = None,
    work_history: list[dict] | None = None,
    projects: list[dict] | None = None,
    evidence_used: list[dict] | None = None,
) -> str:
    """LLM cover letter grounded in resume selection when available."""
    try:
        result = generate(
            _user_prompt(
                candidate=candidate,
                job=job,
                match=match,
                analysis=analysis,
                payload=payload,
                catalog=catalog or [],
                work_history=work_history or [],
                projects=projects or [],
                evidence_used=evidence_used or [],
            ),
            system=COVER_LETTER_SYSTEM,
            temperature=0.3,
            process="coverLetter",
        )
        text = (result.text or "").strip()
        if text:
            return _strip_fences(text)
    except Exception as exc:
        logger.warning("Cover letter LLM failed, using template: %s", exc)
    return fallback_cover(
        candidate=candidate,
        job=job,
        match=match,
        payload=payload,
        catalog=catalog or [],
        evidence_used=evidence_used or [],
    )


def fallback_cover(
    *,
    candidate: dict,
    job: dict,
    match: dict,
    payload: TailorPayload | None = None,
    catalog: list[Achievement] | None = None,
    evidence_used: list[dict] | None = None,
) -> str:
    by_id = {a.id: a for a in (catalog or [])}
    claims: list[str] = []
    if payload:
        rewrite = payload.rewrite_map()
        for sid in payload.selectedAchievementIds[:6]:
            text = rewrite.get(sid) or (
                by_id[sid].statement if sid in by_id else ""
            )
            if text:
                claims.append(f"• {text}")
    if not claims and evidence_used:
        claims = [f"• {e.get('claim')}" for e in evidence_used[:6] if e.get("claim")]

    return f"""{candidate.get('name')}
{candidate.get('location')} | {candidate.get('email')}

{datetime.now(timezone.utc).strftime('%B %d, %Y')}

Dear Hiring Team,

I am applying for the {job.get('title')} position at {job.get('company')}. My background includes enterprise engineering at Capital One and independent product and systems work spanning cloud infrastructure, APIs, and cross-platform applications.

Relevant experience for this role:
{chr(10).join(claims) if claims else '• Verified experience detailed on the accompanying resume.'}

Match assessment for this role: {match.get('score')}/100 ({match.get('recommendation')}).

Thank you for your consideration.

Sincerely,
{candidate.get('name')}
"""


def _user_prompt(
    *,
    candidate: dict,
    job: dict,
    match: dict,
    analysis: JobAnalysis | None,
    payload: TailorPayload | None,
    catalog: list[Achievement],
    work_history: list[dict],
    projects: list[dict],
    evidence_used: list[dict],
) -> str:
    role_family = match.get("roleFamily") or "product"
    by_id = {a.id: a for a in catalog}

    selected_bullets: list[dict[str, Any]] = []
    if payload:
        rewrite = payload.rewrite_map()
        for sid in payload.selectedAchievementIds:
            ach = by_id.get(sid)
            if not ach:
                continue
            selected_bullets.append(
                {
                    "sourceId": sid,
                    "employer": ach.employer,
                    "role": ach.role,
                    "kind": ach.kind,
                    "rewritten": rewrite.get(sid) or ach.statement,
                    "source": ach.statement,
                }
            )

    project_lines = []
    allowed_pids = set(payload.selectedProjectIds) if payload else set()
    for p in projects:
        if allowed_pids and p.get("_id") not in allowed_pids:
            continue
        project_lines.append(f"- {p.get('name')}: {p.get('summary') or ''}")

    work_facts = []
    for role in work_history:
        work_facts.append(
            f"{role.get('title')} at {role.get('company')} "
            f"({role.get('startDate')}–{role.get('endDate') or 'Present'})"
        )

    analysis_block = ""
    if analysis:
        analysis_block = f"""
Job analysis:
Positioning: {analysis.positioning}
Interview deciders: {json.dumps(analysis.interviewDeciders)}
Primary responsibilities: {json.dumps(analysis.primaryResponsibilities[:6])}
Company/cultural signals (from JD only): {json.dumps(analysis.culturalSignals[:6])}
Candidate gaps to acknowledge carefully if needed: {json.dumps(analysis.candidateGaps[:5])}
ATS keywords (use naturally only if true): {json.dumps(analysis.atsKeywords[:15])}
"""

    resume_block = ""
    if payload:
        resume_block = f"""
Resume (final selection — cover letter must reinforce, not copy):
Target headline: {payload.targetRole}
Summary: {payload.summary}
Selected/rewritten achievements (ONLY use these facts):
{json.dumps(selected_bullets[:14], indent=2)}
"""

    evidence_text = "\n".join(
        f"- {e.get('claim')}" for e in evidence_used[:10] if e.get("claim")
    )

    return f"""Write a cover letter for this role.

Candidate: {candidate.get('name')}, {candidate.get('location')}
Email: {candidate.get('email')}
Role family: {role_family}

Target job:
Title: {job.get('title')}
Company: {job.get('company')}
Location: {job.get('location')}
URL: {job.get('url') or '(none)'}
Match score: {match.get('score')}/100 ({match.get('recommendation')})
{analysis_block}
{resume_block}

Official employment (titles/dates are fixed — do not change):
{chr(10).join(work_facts[:12])}

Independent projects (names/summaries only; do not invent impact):
{chr(10).join(project_lines[:6]) or '(none selected)'}

Additional approved evidence claims (use only if consistent with selected resume):
{evidence_text or '(none)'}

Job description excerpt (for company/role language only):
{(job.get('descriptionRaw') or '')[:2000]}

Today's date: {datetime.now(timezone.utc).strftime('%B %d, %Y')}
Sign as {candidate.get('name')}.
Target 300–450 words. Plain text only.
"""


def _strip_fences(text: str) -> str:
    out = text.strip()
    if out.startswith("```"):
        lines = out.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        out = "\n".join(lines).strip()
    return out
