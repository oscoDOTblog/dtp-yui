"""Application package report builders (keywords, fit, talking points, strategy)."""

from __future__ import annotations

import re
from typing import Any

from ..resume.achievements import Achievement
from ..resume.tailor import TailorPayload
from .evidence_ranker import EvidenceRanking
from .job_analyzer import AnalyzedRequirement, JobAnalysis

# Standard layout section labels (shared with resume/layout.py)
_ATS_SECTION_LABELS = (
    "SUMMARY",
    "SELECTED HIGHLIGHTS",
    "CORE EXPERTISE",
    "EXPERIENCE",
    "TECHNOLOGIES",
    "EDUCATION",
)

_STOPWORDS = frozenset(
    {
        "and",
        "the",
        "for",
        "with",
        "from",
        "that",
        "this",
        "your",
        "you",
        "our",
        "are",
        "has",
        "have",
        "will",
        "able",
        "using",
        "experience",
        "strong",
        "knowledge",
        "skills",
        "ability",
        "years",
        "work",
        "working",
        "including",
        "related",
        "etc",
    }
)


def keyword_coverage_markdown(
    *,
    analysis: JobAnalysis,
    resume_text: str,
    cover_text: str,
) -> str:
    present, missing, coverage = _keyword_sets(analysis, resume_text, cover_text)
    lines = ["# ATS keyword coverage", ""]
    if not analysis.atsKeywords:
        lines.append("No ATS keywords extracted.")
        return "\n".join(lines) + "\n"

    lines.append(
        f"**Coverage:** {len(present)}/{len(analysis.atsKeywords)} ({coverage:.0f}%)"
    )
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
    catalog: list[Achievement] | None = None,
    skills: list[dict] | None = None,
    critic_scores: dict[str, Any] | None = None,
    resume_text: str = "",
    cover_text: str = "",
) -> str:
    catalog = catalog or []
    skills = skills or []
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

    match_rows = build_requirement_evidence_rows(
        analysis=analysis,
        payload=payload,
        catalog=catalog,
        skills=skills,
        limit=12,
    )
    lines += ["", "## Requirement × evidence match"]
    lines.append("| Requirement | Priority | Status | Evidence |")
    lines.append("|---|---|---|---|")
    if match_rows:
        for row in match_rows:
            lines.append(
                f"| {_md_cell(row['requirement'])} | {row['priority']} | "
                f"{row['status']} | {_md_cell(row['evidence'])} |"
            )
    else:
        lines.append("| (no critical/important requirements extracted) | — | — | — |")

    lines += ["", "## Competitive strengths"]
    covered_critical = [
        r for r in match_rows if r["status"] == "covered" and r["priority"] == "critical"
    ]
    covered_any = [r for r in match_rows if r["status"] == "covered"]
    strength_src = covered_critical or covered_any
    if strength_src:
        for r in strength_src[:3]:
            sid_bit = r["evidence"].split(" — ")[0] if r["evidence"] != "—" else "selected evidence"
            lines.append(
                f"- Covers **{r['requirement']}** via selected work/projects ({sid_bit})."
            )
    else:
        strengths = [m.get("requirement") for m in (match.get("strongMatches") or [])[:3]]
        if not strengths and payload.summary:
            strengths = [payload.summary[:120]]
        for s in strengths:
            if s:
                lines.append(f"- {s}")
        if not strengths:
            lines.append("- See selected resume achievements.")

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

    lines += ["", "## Intentional omissions"]
    gap_reqs = [r for r in match_rows if r["status"] == "gap"]
    _, missing_kw, _ = _keyword_sets(analysis, resume_text, cover_text)
    omission_notes: list[str] = []
    for r in gap_reqs[:6]:
        omission_notes.append(
            f"- **{r['requirement']}** — left off because not supported by verified catalog evidence."
        )
    for kw in missing_kw[:6]:
        if any(kw.lower() in n.lower() for n in omission_notes):
            continue
        omission_notes.append(
            f"- Keyword **{kw}** — not explicit in package; left off when not in verified experience."
        )
    for item in (payload.omittedRequirements or [])[:6]:
        omission_notes.append(
            f"- {item} — de-emphasized; left off because not in verified catalog or weak fit."
        )
    if omission_notes:
        lines.extend(omission_notes[:10])
    else:
        lines.append("- None noted.")

    if critic_scores:
        lines += ["", "## Resume critic scores (1–10)"]
        for k, v in critic_scores.items():
            if k in ("mustFix", "optionalImprove", "mean", "provider"):
                continue
            lines.append(f"- {k}: {v}")
        if critic_scores.get("mean") is not None:
            lines.append(f"- **mean:** {critic_scores['mean']}")

    lines += ["", "## Omitted JD items (resume)"]
    if payload.omittedRequirements:
        for item in payload.omittedRequirements:
            lines.append(f"- {item}")
    else:
        lines.append("- None listed.")
    lines.append("")
    return "\n".join(lines)


def build_requirement_evidence_rows(
    *,
    analysis: JobAnalysis,
    payload: TailorPayload,
    catalog: list[Achievement],
    skills: list[dict],
    limit: int = 12,
) -> list[dict[str, str]]:
    """Map critical/important requirements to selected evidence or gap."""
    by_id = {a.id: a for a in catalog}
    rewrite = payload.rewrite_map()
    skill_by_id = {s["_id"]: s for s in skills if s.get("_id")}

    evidence_units: list[tuple[str, str, str]] = []
    for sid in payload.selectedAchievementIds:
        ach = by_id.get(sid)
        text = (rewrite.get(sid) or (ach.statement if ach else "") or "").strip()
        if not text:
            continue
        evidence_units.append((sid, text.lower(), text[:100]))
    for sid in payload.selectedSkillIds:
        skill = skill_by_id.get(sid)
        if not skill or not skill.get("name"):
            continue
        name = str(skill["name"])
        evidence_units.append((f"skill:{sid}", name.lower(), name))
    for h in payload.highlights or []:
        text = (h.text or "").strip()
        sid = str(h.sourceId or "")
        if text and not sid.startswith("milestone:"):
            evidence_units.append((sid, text.lower(), text[:100]))

    reqs = [
        r
        for r in analysis.requirements
        if r.class_ in ("critical", "important") and (r.text or "").strip()
    ][:limit]
    if not reqs:
        reqs = [
            AnalyzedRequirement.model_validate({"text": t, "class": "important"})
            for t in analysis.requiredQualifications[:limit]
            if t.strip()
        ]

    rows: list[dict[str, str]] = []
    for req in reqs[:limit]:
        text = req.text.strip()
        status = "gap"
        evidence = "—"
        hay_bits = re.findall(r"[a-z0-9][a-z0-9+.#/-]{1,}", text.lower())
        hay_bits = [b for b in hay_bits if len(b) > 2 and b not in _STOPWORDS]
        for eid, elower, edisp in evidence_units:
            if _requirement_supported(text, elower, hay_bits):
                status = "covered"
                snippet = edisp if len(edisp) <= 80 else edisp[:77] + "…"
                evidence = f"`{eid}` — {snippet}"
                break
        rows.append(
            {
                "requirement": text,
                "priority": req.class_,
                "status": status,
                "evidence": evidence,
            }
        )
    return rows


def _requirement_supported(
    requirement: str, evidence_lower: str, tokens: list[str]
) -> bool:
    req_l = requirement.lower()
    if len(req_l) >= 8 and req_l in evidence_lower:
        return True
    if not tokens:
        return False
    hits = sum(1 for t in tokens if t in evidence_lower)
    if len(tokens) == 1:
        return hits >= 1
    if len(tokens) == 2:
        return hits >= 2
    # Short tech tokens (aws, sql, k8s, …) are decisive when present in evidence
    short_hits = [t for t in tokens if len(t) <= 5 and t in evidence_lower]
    if short_hits:
        return True
    return hits >= max(2, (len(tokens) + 1) // 2)


def ats_checklist_markdown(
    *,
    resume_text: str,
    analysis: JobAnalysis | None = None,
    cover_text: str = "",
    keyword_coverage_pct: float | None = None,
) -> str:
    """Deterministic ATS/machine readability checks on rendered resume text."""
    text = resume_text or ""
    lines_all = text.splitlines()
    nonempty = [ln for ln in lines_all if ln.strip()]
    upper_text = text

    checks: list[tuple[str, bool, str]] = []
    for label in _ATS_SECTION_LABELS:
        present = any(
            ln.strip() == label or ln.strip().startswith(label) for ln in lines_all
        )
        checks.append(
            (
                f"Section `{label}` present",
                present,
                "ok" if present else "missing (may be fine if empty content)",
            )
        )
    independent = any(
        "INDEPENDENT SOFTWARE ENGINEER" in ln.upper() for ln in lines_all
    )
    checks.append(
        (
            "Independent / projects section header",
            independent or "EXPERIENCE" in upper_text,
            "ok" if independent else "no independent header (ok if no project bullets)",
        )
    )

    has_tailored_footer = bool(re.search(r"tailored for\s*:", text, flags=re.I))
    checks.append(
        (
            "No 'Tailored for…' footer",
            not has_tailored_footer,
            "ok" if not has_tailored_footer else "remove marketing footer from artifact",
        )
    )

    has_https = "https://" in text.lower() or "http://" in text.lower()
    checks.append(
        (
            "Contact URLs cleaned (no raw https://)",
            not has_https,
            "ok" if not has_https else "prefer linkedin.com/… without scheme",
        )
    )

    n_lines = len(nonempty)
    length_ok = 15 <= n_lines <= 200
    checks.append(
        (
            f"Reasonable length ({n_lines} non-empty lines)",
            length_ok,
            "ok" if length_ok else "unexpectedly short or long plain-text resume",
        )
    )

    has_name_first = bool(nonempty and len(nonempty[0]) < 80)
    checks.append(
        (
            "Headline/name block present",
            has_name_first and "SUMMARY" in upper_text,
            "ok" if has_name_first else "missing header block",
        )
    )

    if keyword_coverage_pct is None and analysis is not None:
        _, _, keyword_coverage_pct = _keyword_sets(
            analysis, resume_text, cover_text
        )

    lines = [
        "# ATS checklist (deterministic)",
        "",
        "Machine-oriented checks on the rendered plain-text resume. Not a guarantee of ATS pass.",
        "",
    ]
    if keyword_coverage_pct is not None and analysis and analysis.atsKeywords:
        lines.append(
            f"**Keyword coverage (package):** {keyword_coverage_pct:.0f}% "
            f"of extracted ATS keywords present in resume/cover."
        )
        lines.append("")

    lines.append("| Check | Result | Note |")
    lines.append("|---|---|---|")
    for name, ok, note in checks:
        result = "pass" if ok else "review"
        lines.append(f"| {name} | {result} | {_md_cell(note)} |")
    lines.append("")
    return "\n".join(lines)


def selection_changelog_markdown(
    *,
    before: TailorPayload | dict[str, Any],
    after: TailorPayload | dict[str, Any],
    job: dict | None = None,
) -> str:
    """Deterministic diff of selection when critic triggers a revise pass."""
    b = before.to_report() if isinstance(before, TailorPayload) else dict(before)
    a = after.to_report() if isinstance(after, TailorPayload) else dict(after)

    b_ids = set(b.get("selectedAchievementIds") or [])
    a_ids = set(a.get("selectedAchievementIds") or [])
    added = sorted(a_ids - b_ids)
    removed = sorted(b_ids - a_ids)

    b_hl: set[str] = set()
    a_hl: set[str] = set()
    if isinstance(before, TailorPayload):
        b_hl = {h.sourceId for h in before.highlights}
    else:
        b_hl = {
            str(h.get("sourceId"))
            for h in (b.get("highlights") or [])
            if isinstance(h, dict) and h.get("sourceId")
        }
    if isinstance(after, TailorPayload):
        a_hl = {h.sourceId for h in after.highlights}
    else:
        a_hl = {
            str(h.get("sourceId"))
            for h in (a.get("highlights") or [])
            if isinstance(h, dict) and h.get("sourceId")
        }
    hl_added = sorted(a_hl - b_hl)
    hl_removed = sorted(b_hl - a_hl)

    b_sum = str(b.get("summary") or "")
    a_sum = str(a.get("summary") or "")
    title = ""
    if job:
        title = f" — {job.get('title')} @ {job.get('company')}"

    lines = [
        f"# Selection changelog{title}",
        "",
        "Deterministic diff after resume critic revision (sourceIds only; no invented claims).",
        "",
        "## Achievement selection",
        f"- Before: {len(b_ids)} · After: {len(a_ids)}",
    ]
    if added:
        lines.append("- **Added:**")
        for sid in added:
            lines.append(f"  - `{sid}`")
    else:
        lines.append("- **Added:** (none)")
    if removed:
        lines.append("- **Removed:**")
        for sid in removed:
            lines.append(f"  - `{sid}`")
    else:
        lines.append("- **Removed:** (none)")

    lines += [
        "",
        "## Summary length",
        f"- Before: {len(b_sum)} chars · After: {len(a_sum)} chars "
        f"(Δ {len(a_sum) - len(b_sum):+d})",
    ]

    lines += ["", "## Highlights sourceIds"]
    if hl_added:
        lines.append("- **Added:** " + ", ".join(f"`{x}`" for x in hl_added))
    else:
        lines.append("- **Added:** (none)")
    if hl_removed:
        lines.append("- **Removed:** " + ", ".join(f"`{x}`" for x in hl_removed))
    else:
        lines.append("- **Removed:** (none)")

    b_skills = set(b.get("selectedSkillIds") or [])
    a_skills = set(a.get("selectedSkillIds") or [])
    skill_added = sorted(a_skills - b_skills)
    skill_removed = sorted(b_skills - a_skills)
    lines += [
        "",
        "## Skills",
        f"- Before: {len(b_skills)} · After: {len(a_skills)}",
    ]
    if skill_added[:8]:
        lines.append(
            "- **Added (sample):** " + ", ".join(f"`{x}`" for x in skill_added[:8])
        )
    if skill_removed[:8]:
        lines.append(
            "- **Removed (sample):** " + ", ".join(f"`{x}`" for x in skill_removed[:8])
        )

    if not added and not removed and b_sum == a_sum and not hl_added and not hl_removed:
        lines += ["", "_Selection was unchanged after revision pass._"]

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
        + ", ".join(
            analysis.interviewDeciders[:4]
            or [m.get("requirement") for m in (match.get("strongMatches") or [])[:4]]
        )
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


def _keyword_sets(
    analysis: JobAnalysis,
    resume_text: str,
    cover_text: str,
) -> tuple[list[str], list[str], float]:
    combined = f"{resume_text}\n{cover_text}".lower()
    present: list[str] = []
    missing: list[str] = []
    for kw in analysis.atsKeywords:
        if _keyword_present(kw, combined):
            present.append(kw)
        else:
            missing.append(kw)
    coverage = (
        100.0 * len(present) / len(analysis.atsKeywords) if analysis.atsKeywords else 0.0
    )
    return present, missing, coverage


def _keyword_present(keyword: str, haystack: str) -> bool:
    kw = (keyword or "").strip().lower()
    if not kw:
        return False
    if kw in haystack:
        return True
    parts = [p for p in re.split(r"[\s,/|+]+", kw) if len(p) > 2]
    if len(parts) >= 2 and all(p in haystack for p in parts):
        return True
    return False


def _md_cell(value: str) -> str:
    return (value or "").replace("|", "\\|").replace("\n", " ").strip()
