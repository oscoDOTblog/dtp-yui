"""Application package report builders (keywords, fit, talking points, strategy)."""

from __future__ import annotations

import re
from typing import Any

from ..resume.achievements import Achievement
from ..resume.tailor import TailorPayload
from .evidence_ranker import EvidenceRanking
from .job_analyzer import JobAnalysis


def keyword_coverage_markdown(
    *,
    analysis: JobAnalysis,
    resume_text: str,
    cover_text: str,
) -> str:
    combined = f"{resume_text}\n{cover_text}".lower()
    lines = ["# ATS keyword coverage", ""]
    if not analysis.atsKeywords:
        lines.append("No ATS keywords extracted.")
        return "\n".join(lines) + "\n"

    present: list[str] = []
    missing: list[str] = []
    for kw in analysis.atsKeywords:
        if _keyword_present(kw, combined):
            present.append(kw)
        else:
            missing.append(kw)

    coverage = (
        100.0 * len(present) / len(analysis.atsKeywords) if analysis.atsKeywords else 0
    )
    lines.append(f"**Coverage:** {len(present)}/{len(analysis.atsKeywords)} ({coverage:.0f}%)")
    lines += ["", "## Present in application package"]
    if present:
        for kw in present:
            lines.append(f"- {kw}")
    else:
        lines.append("- (none)")
    lines += ["", "## Missing or not explicit"]
    if missing:
        for kw in missing:
            lines.append(f"- {kw}")
    else:
        lines.append("- (none)")
    lines += [
        "",
        "_Missing keywords are intentional when the candidate lacks verified experience — do not invent coverage._",
        "",
    ]
    return "\n".join(lines)


def fit_assessment_markdown(
    *,
    job: dict,
    match: dict,
    analysis: JobAnalysis,
    payload: TailorPayload,
    critic_scores: dict[str, Any] | None = None,
) -> str:
    score = match.get("score")
    lines = [
        f"# Candidate-to-role fit — {job.get('title')} @ {job.get('company')}",
        "",
        f"**Match score:** {score}/100 ({match.get('recommendation')})",
        f"**Positioning:** {analysis.positioning or payload.targetRole or '—'}",
        "",
        "## Interview deciders",
    ]
    for d in analysis.interviewDeciders or ["(none extracted)"]:
        lines.append(f"- {d}")

    lines += ["", "## Key strengths for this application"]
    strengths = [m.get("requirement") for m in (match.get("strongMatches") or [])[:8]]
    if not strengths and payload.summary:
        strengths = [payload.summary]
    for s in strengths:
        if s:
            lines.append(f"- {s}")
    if not strengths:
        lines.append("- See selected resume achievements.")

    lines += ["", "## Material gaps / risks"]
    gaps = analysis.candidateGaps or [
        g.get("skill") or g.get("requirement")
        for g in (match.get("meaningfulGaps") or [])
    ]
    if gaps:
        for g in gaps[:8]:
            if g:
                lines.append(f"- {g}")
    else:
        lines.append("- None flagged as material.")

    if critic_scores:
        lines += ["", "## Resume critic scores (1–10)"]
        for k, v in critic_scores.items():
            if k in ("mustFix", "optionalImprove", "mean", "provider"):
                continue
            lines.append(f"- {k}: {v}")
        if critic_scores.get("mean") is not None:
            lines.append(f"- **mean:** {critic_scores['mean']}")

    lines += [
        "",
        f"## Omitted JD items (resume)",
    ]
    if payload.omittedRequirements:
        for item in payload.omittedRequirements:
            lines.append(f"- {item}")
    else:
        lines.append("- None listed.")
    lines.append("")
    return "\n".join(lines)


def talking_points_markdown(
    *,
    job: dict,
    analysis: JobAnalysis,
    payload: TailorPayload,
    catalog: list[Achievement],
) -> str:
    by_id = {a.id: a for a in catalog}
    rewrite = payload.rewrite_map()
    lines = [
        f"# Interview talking points — {job.get('title')} @ {job.get('company')}",
        "",
        "Use these as conversation anchors. Stay factual to verified experience.",
        "",
        "## Role positioning",
        f"- Headline: {payload.targetRole or analysis.positioning or '—'}",
    ]
    if payload.summary:
        lines.append(f"- Summary cue: {payload.summary}")

    lines += ["", "## Evidence stories (from tailored resume)"]
    for sid in payload.selectedAchievementIds[:6]:
        ach = by_id.get(sid)
        text = rewrite.get(sid) or (ach.statement if ach else "")
        if not text:
            continue
        ctx = ""
        if ach:
            ctx = f" ({ach.employer or ach.title or ach.kind})"
        lines.append(f"- {text}{ctx}")

    if analysis.interviewDeciders:
        lines += ["", "## Likely interview themes"]
        for d in analysis.interviewDeciders:
            lines.append(f"- {d}")

    if analysis.candidateGaps:
        lines += ["", "## Gaps — honest framing"]
        for g in analysis.candidateGaps[:5]:
            lines.append(
                f"- {g}: discuss transferable/related work without overstating."
            )

    lines.append("")
    return "\n".join(lines)


def tailoring_strategy_markdown(
    *,
    job: dict,
    analysis: JobAnalysis,
    ranking: EvidenceRanking,
    payload: TailorPayload,
    pipeline_meta: dict[str, Any],
) -> str:
    top = ranking.ordered_ids(limit=8)
    lines = [
        f"# Tailoring strategy — {job.get('title')} @ {job.get('company')}",
        "",
        f"**Pipeline:** {pipeline_meta.get('pipeline', 'openai-multistage')}",
        f"**Positioning headline:** {payload.targetRole or analysis.positioning}",
        "",
        "## Why this packaging",
        f"- Interview deciders: {', '.join(analysis.interviewDeciders) or '—'}",
        f"- Selected {len(payload.selectedAchievementIds)} achievements; "
        f"{len(payload.highlights)} highlights.",
        f"- Ranking source: {ranking.source}"
        + (f" ({ranking.provider})" if ranking.provider else ""),
        "",
        "## Top-ranked evidence used",
    ]
    score_map = ranking.score_map()
    for sid in payload.selectedAchievementIds[:10]:
        score = score_map.get(sid)
        score_s = f"score {score:.0f}" if score is not None else "score n/a"
        lines.append(f"- `{sid}` ({score_s})")

    if top:
        lines += ["", "## Ranker top IDs (for reference)"]
        for sid in top:
            lines.append(f"- `{sid}` ({score_map.get(sid, 0):.0f})")

    if payload.omittedRequirements:
        lines += ["", "## Consciously de-emphasized"]
        for item in payload.omittedRequirements:
            lines.append(f"- {item}")

    lines += [
        "",
        "## Cover letter focus",
        "- Motive + interpretation; resume holds raw evidence.",
        "- Same selected sources only; no new claims.",
        "",
    ]
    return "\n".join(lines)


def application_report(
    *,
    job: dict,
    match: dict,
    analysis: JobAnalysis,
    ranking: EvidenceRanking,
    payload: TailorPayload,
    critic: dict[str, Any] | None,
    consistency: dict[str, Any] | None,
    pipeline_meta: dict[str, Any],
    evidence_ids_used: list[str],
) -> dict[str, Any]:
    return {
        "jobId": job.get("_id"),
        "title": job.get("title"),
        "company": job.get("company"),
        "matchScore": match.get("score"),
        "recommendation": match.get("recommendation"),
        "pipeline": pipeline_meta.get("pipeline"),
        "stages": pipeline_meta.get("stages"),
        "positioning": analysis.positioning or payload.targetRole,
        "atsKeywords": list(analysis.atsKeywords),
        "interviewDeciders": list(analysis.interviewDeciders),
        "selectedAchievementIds": list(payload.selectedAchievementIds),
        "highlightSourceIds": [h.sourceId for h in payload.highlights],
        "selectedSkillIds": list(payload.selectedSkillIds),
        "selectedProjectIds": list(payload.selectedProjectIds),
        "omittedRequirements": list(payload.omittedRequirements),
        "evidenceIdsUsed": list(evidence_ids_used),
        "rankingSource": ranking.source,
        "critic": critic,
        "consistency": consistency,
        "candidateGaps": list(analysis.candidateGaps),
    }


def enhanced_application_answers(
    *,
    candidate: dict,
    job: dict,
    match: dict,
    analysis: JobAnalysis,
    payload: TailorPayload,
    evidence_used: list[dict],
    talking_points_md: str,
) -> str:
    why = (
        f"I am interested in {job.get('company')} because the role ({job.get('title')}) "
        f"aligns with my experience as {payload.targetRole or analysis.positioning or (match.get('roleFamily') or 'product') + ' engineer'}. "
        f"Key fit themes: "
        + ", ".join(analysis.interviewDeciders[:4] or [m.get("requirement") for m in (match.get("strongMatches") or [])[:4]])
        + "."
    )
    gaps = analysis.candidateGaps or [
        g.get("skill") for g in (match.get("meaningfulGaps") or [])
    ]
    gap_block = (
        "\n".join(f"- {g}" for g in gaps[:5] if g)
        if gaps
        else "- None flagged as critical."
    )
    evidence_block = "\n".join(
        f"- [{e['_id']}] {e.get('claim')}" for e in evidence_used[:10]
    )
    strengths = "\n".join(
        f"- {m.get('requirement')}"
        for m in (match.get("strongMatches") or [])[:10]
        if m.get("requirement")
    ) or "- See tailored resume highlights."

    # Condensed talking points (skip header)
    tp_body = talking_points_md
    if tp_body.startswith("#"):
        tp_body = "\n".join(tp_body.splitlines()[1:]).strip()

    return f"""# Application answers — {job.get('title')} @ {job.get('company')}

## Why do you want to work here?
{why}

## Qualification summary
Match score: **{match.get('score')}/100** ({match.get('recommendation')})
Positioning: {payload.targetRole or analysis.positioning or '—'}

### Strong evidence
{strengths}

### Meaningful gaps
{gap_block}

### Why still viable
{match.get('whyViable') or 'See fit assessment; emphasize transferable systems ownership and verified skills.'}

## Interview talking points
{tp_body[:2500]}

## Portfolio / evidence to attach
{evidence_block}

## Missing-information checklist
- [ ] Confirm work authorization / location requirements
- [ ] Confirm salary range vs minimum (${candidate.get('minimumSalary')})
- [ ] Review generated resume and cover letter before submit
- [ ] Open application URL and submit manually (Level 1)

## Recruiter message (short)
Hi — I'm {candidate.get('name')}, applying for {job.get('title')}. Happy to share a tailored resume emphasizing my most relevant experience for this team.
"""


def _keyword_present(keyword: str, haystack: str) -> bool:
    kw = (keyword or "").strip().lower()
    if not kw:
        return False
    if kw in haystack:
        return True
    # Token-ish match for multi-word
    parts = [p for p in re.split(r"[\s,/|+]+", kw) if len(p) > 2]
    if len(parts) >= 2 and all(p in haystack for p in parts):
        return True
    return False
