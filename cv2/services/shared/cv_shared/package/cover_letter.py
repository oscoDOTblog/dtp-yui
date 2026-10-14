"""Cover letter composer with narrative business-letter voice."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from ..llm import generate
from ..resume.achievements import Achievement
from ..resume.tailor import TailorPayload
from .job_analyzer import JobAnalysis
from .prompts import COVER_LETTER_SYSTEM

logger = logging.getLogger(__name__)

_MONTH_LINE = re.compile(
    r"^(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},\s+\d{4}\s*$",
    re.I,
)


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
    date_line = _format_date_line()

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
                date_line=date_line,
            ),
            system=COVER_LETTER_SYSTEM,
            temperature=0.45,
            process="coverLetter",
        )
        text = (result.text or "").strip()
        if text:
            return ensure_letter_envelope(
                _strip_fences(text),
                candidate=candidate,
                job=job,
                date_line=date_line,
            )
    except Exception as exc:
        logger.warning("Cover letter LLM failed, using template: %s", exc)
    return fallback_cover(
        candidate=candidate,
        job=job,
        match=match,
        payload=payload,
        catalog=catalog or [],
        evidence_used=evidence_used or [],
        date_line=date_line,
    )


def fallback_cover(
    *,
    candidate: dict,
    job: dict,
    match: dict,
    payload: TailorPayload | None = None,
    catalog: list[Achievement] | None = None,
    evidence_used: list[dict] | None = None,
    date_line: str | None = None,
) -> str:
    """Structured business-letter template (not a claim bullet list)."""
    date_line = date_line or _format_date_line()
    company = job.get("company") or "the company"
    title = job.get("title") or "this role"
    name = candidate.get("name") or "Candidate"
    role_family = match.get("roleFamily") or "product"

    by_id = {a.id: a for a in (catalog or [])}
    theme_bits: list[str] = []
    if payload:
        rewrite = payload.rewrite_map()
        for sid in payload.selectedAchievementIds[:3]:
            text = rewrite.get(sid) or (
                by_id[sid].statement if sid in by_id else ""
            )
            if text:
                # One short clause, not a bullet dump
                theme_bits.append(text.rstrip(".")[:140])

    arc = (
        f"Over my career I have focused on building and operating production systems—"
        f"particularly work that improves reliability, delivery workflows, and how "
        f"teams ship software. My experience in {(role_family)} engineering at "
        f"organizations like Capital One has emphasized ownership from implementation "
        f"through production support."
    )
    if theme_bits:
        arc += (
            f" Themes from my most relevant work include "
            f"{theme_bits[0].lower()}"
            + (f", and {theme_bits[1].lower()}" if len(theme_bits) > 1 else "")
            + "."
        )

    body = f"""I'm excited to apply for the {title} position at {company}. The most rewarding engineering work for me has been building platforms, tooling, and infrastructure that make software delivery more reliable and developers more effective—not only shipping surface-level features.

{arc}

What draws me to {company} is the opportunity to apply that background to this team's problems as described in the role: improving systems other engineers depend on, with a focus on production quality and long-term maintainability. I would welcome the chance to contribute in an environment that values ownership and operational excellence.

I'd welcome the opportunity to discuss how I could contribute to {company}'s engineering organization.

Thank you for your time and consideration. I look forward to the opportunity to speak with you.

Sincerely,

{name}
"""
    return ensure_letter_envelope(
        body.strip(),
        candidate=candidate,
        job=job,
        date_line=date_line,
    )


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
    date_line: str,
) -> str:
    role_family = match.get("roleFamily") or "product"
    by_id = {a.id: a for a in catalog}
    company = job.get("company") or "Company"
    name = candidate.get("name") or "Candidate"

    # Slim grounding notes (2–4 achievements), not a full inventory dump
    ground_notes: list[dict[str, Any]] = []
    if payload:
        rewrite = payload.rewrite_map()
        for sid in payload.selectedAchievementIds[:4]:
            ach = by_id.get(sid)
            if not ach:
                continue
            ground_notes.append(
                {
                    "employer": ach.employer,
                    "role": ach.role,
                    "kind": ach.kind,
                    "note": rewrite.get(sid) or ach.statement,
                }
            )

    work_lines = []
    for role in work_history[:8]:
        work_lines.append(
            f"- {role.get('title')} at {role.get('company')} "
            f"({role.get('startDate')}–{role.get('endDate') or 'Present'})"
        )

    project_blocks: list[str] = []
    allowed_pids = set(payload.selectedProjectIds) if payload else set()
    for p in projects:
        if allowed_pids and p.get("_id") not in allowed_pids:
            continue
        bullets = list(p.get("resumeBullets") or [])[:2]
        block = f"- {p.get('name')}: {p.get('summary') or ''}".strip()
        if bullets:
            block += "\n  notes: " + " | ".join(str(b) for b in bullets)
        project_blocks.append(block)
        if len(project_blocks) >= 5:
            break

    analysis_block = ""
    if analysis:
        analysis_block = f"""
Role themes from job analysis (compose around these; do not list as a scorecard):
Positioning headline: {analysis.positioning}
Interview deciders: {json.dumps(analysis.interviewDeciders)}
Primary responsibilities: {json.dumps(analysis.primaryResponsibilities[:6])}
Cultural signals from JD: {json.dumps(analysis.culturalSignals[:8])}
Candidate gaps (do not invent coverage; only soft transfer if natural): {json.dumps(analysis.candidateGaps[:4])}
"""

    resume_summary = ""
    if payload:
        resume_summary = f"""
Resume positioning (do not copy; reinforce the narrative):
Headline: {payload.targetRole}
Summary: {payload.summary}

Grounding notes only — INTERPRET as career themes, never inventory as a list of bullets
or pack many tools into one sentence (use at most 2–4 of these notes):
{json.dumps(ground_notes, indent=2)}
"""

    evidence_text = "\n".join(
        f"- {e.get('claim')}" for e in (evidence_used or [])[:6] if e.get("claim")
    )

    return f"""Write a FULL business-letter cover letter for this application.

Evidence is for grounding only—tell a coherent career and motivation story.
Do NOT paste the resume. Do NOT mention match scores. Do NOT use bullet lists.

Candidate name (sign as): {name}
Location (context only, not required in header): {candidate.get('location')}
Role family emphasis: {role_family}

Target job:
Exact title: {job.get('title')}
Company: {company}
Location: {job.get('location')}
URL: {job.get('url') or '(none)'}
{analysis_block}
{resume_summary}

Official employment (titles and dates fixed—do not change; elevation-only narrative):
{chr(10).join(work_lines) or '(none)'}

Independent projects (include a differentiator paragraph only if listed; do not invent impact):
{chr(10).join(project_blocks) if project_blocks else '(none selected — omit independent-work paragraph)'}

Additional approved claims (only if consistent with selected resume; do not invent):
{evidence_text or '(none)'}

Job description excerpt (use for company/role language and culture only):
{(job.get('descriptionRaw') or '')[:2500]}

Envelope (required):
- Date line: {date_line}
- Recipient: Hiring Team / {company}
- Salutation: Dear Hiring Team,
- Close with: I'd welcome the opportunity… then Thank you for your time and consideration… then Sincerely, then {name}

Target ~400–550 words for the full letter. Plain text only.
"""


def _format_date_line() -> str:
    now = datetime.now(timezone.utc)
    try:
        return now.strftime("%B %-d, %Y")  # POSIX: no zero-pad day
    except ValueError:
        return now.strftime("%B %d, %Y").replace(" 0", " ")


def ensure_letter_envelope(
    text: str,
    *,
    candidate: dict,
    job: dict,
    date_line: str | None = None,
) -> str:
    """Ensure date, Hiring Team / company, salutation, and Sincerely sign-off."""
    return _ensure_letter_envelope(
        text,
        candidate=candidate,
        job=job,
        date_line=date_line or _format_date_line(),
    )


def _ensure_letter_envelope(
    text: str,
    *,
    candidate: dict,
    job: dict,
    date_line: str,
) -> str:
    """Ensure date, Hiring Team / company, salutation, and Sincerely sign-off."""
    body = (text or "").strip()
    if not body:
        return body

    company = str(job.get("company") or "Company").strip()
    name = str(candidate.get("name") or "Candidate").strip()
    lines = body.splitlines()
    first = (lines[0] or "").strip() if lines else ""

    has_date = bool(_MONTH_LINE.match(first))
    lower = body.lower()
    has_hiring_team_block = "hiring team" in lower[:400]
    has_sincerely = bool(re.search(r"(?m)^\s*sincerely,?\s*$", body, re.I))
    has_dear = bool(re.search(r"(?im)^\s*dear\s+", body))

    # Strip accidental leading contact/name header that isn't the date envelope
    if not has_date and first and "@" in first:
        # contact line at top — drop until blank or Dear
        idx = 0
        while idx < len(lines) and lines[idx].strip() and not re.match(
            r"(?i)^dear\s+", lines[idx].strip()
        ):
            idx += 1
        body = "\n".join(lines[idx:]).strip()
        lines = body.splitlines()
        first = (lines[0] or "").strip() if lines else ""
        has_date = bool(_MONTH_LINE.match(first))
        lower = body.lower()
        has_hiring_team_block = "hiring team" in lower[:400]
        has_sincerely = bool(re.search(r"(?m)^\s*sincerely,?\s*$", body, re.I))
        has_dear = bool(re.search(r"(?im)^\s*dear\s+", body))

    if not has_date or not has_hiring_team_block:
        # Strip an existing incomplete head up to Dear ... if present
        dear_match = re.search(r"(?im)^\s*dear\s+.+$", body)
        body_start = body
        if dear_match:
            body_start = body[dear_match.start() :].strip()
        elif not has_dear:
            body_start = f"Dear Hiring Team,\n\n{body}"

        header = f"{date_line}\n\nHiring Team\n{company}\n\n"
        body = header + body_start
        has_sincerely = bool(re.search(r"(?m)^\s*sincerely,?\s*$", body, re.I))

    if not has_sincerely:
        # Avoid double-adding if name alone at end
        trimmed = body.rstrip()
        close = (
            "\n\nI'd welcome the opportunity to discuss how I could contribute.\n\n"
            "Thank you for your time and consideration. "
            "I look forward to the opportunity to speak with you.\n\n"
            f"Sincerely,\n\n{name}\n"
        )
        # If a weak "Sincerely" variant missing, or name without Sincerely
        if re.search(r"(?i)sincerely", trimmed) and name in trimmed[-80:]:
            pass
        elif trimmed.endswith(name):
            body = trimmed[: -len(name)].rstrip() + f"\n\nSincerely,\n\n{name}\n"
        else:
            body = trimmed + close

    # Ensure name after Sincerely
    if re.search(r"(?im)^\s*sincerely,?\s*$", body) and name not in body[-120:]:
        body = body.rstrip() + f"\n\n{name}\n"

    return body.strip() + "\n"


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
