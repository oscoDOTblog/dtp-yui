---
name: Mine resume skill concepts
overview: Mine a handful of concrete patterns from public resume-tailor skills into the existing grounded multi-stage CV package pipeline—reports, prompts, and deterministic checklists—without installing those skills or relaxing invent-nothing rules.
todos:
  - id: prompts-mine
    content: "Update RESUME_COMPOSER/CRITIC/ANALYZER prompts: grounded impact formula, verb diversity, dual-form keywords"
    status: completed
  - id: reports-match-table
    content: Add requirement×evidence table + strengths/omissions + ATS checklist to reports.py
    status: completed
  - id: pipeline-changelog
    content: Wire new artifacts and deterministic selection-changelog when critic revises
    status: completed
  - id: docs-pipeline
    content: Document mined artifacts in RESUME_PIPELINE.md
    status: completed
isProject: false
---

# Mine external resume-skill concepts into CV pipeline

## Intent

Extract useful **patterns** from [tailored-resume-generator](https://www.skills.sh/composiohq/awesome-claude-skills/tailored-resume-generator), [resume-tailor](https://www.skills.sh/claude-office-skills/skills/resume-tailor), and [resume-ats-optimizer](https://www.skills.sh/paramchoudhary/resumeskills/resume-ats-optimizer) into the **existing** multi-stage package path. Do **not** install those skills or open a freeform paste-JD→resume path.

Grounding stays absolute: no invented metrics, employers, titles, tech, or tools.

## Already covered (skip re-implementing)

| External idea | Existing home |
|---|---|
| JD requirement priority | `critical` / `important` / `helpful` in job analyzer |
| Keyword extraction + coverage | `atsKeywords` + [`keyword_coverage_markdown`](cv/services/shared/cv_shared/package/reports.py) |
| Evidence ranking by relevance | [`evidence_ranker.py`](cv/services/shared/cv_shared/package/evidence_ranker.py) |
| ATS section headings / layout | [`layout.py`](cv/services/shared/cv_shared/resume/layout.py) fixed labels |
| Dual CapOne + independent profile | layout + project floor + composer prompt |
| Critic multi-persona pass | [`resume_critic.py`](cv/services/shared/cv_shared/package/resume_critic.py) |
| Gaps / strategy / talking points | package report builders |

## Concepts worth mining (concrete)

### 1. Requirement → evidence match table (from resume-tailor “match matrix”)

Extend [`fit_assessment_markdown`](cv/services/shared/cv_shared/package/reports.py) with a short table:

```text
| Requirement (priority) | Status | Evidence |
| critical AWS / CI…     | covered | work:…:b0 (snippet) |
| Go microservice…       | gap    | — |
```

Rules:
- **covered** only if an approved selected achievement or skill text supports it (reuse / soft-match like keyword coverage).
- **gap** when not grounded — never invent filling text.
- Cap rows (~12 critical/important only).

### 2. Grounded impact formula (from both tailor skills)

Add to `RESUME_COMPOSER_SYSTEM` in [`prompts.py`](cv/services/shared/cv_shared/package/prompts.py):

- Prefer rewrite shape: **Action + what + how + result** *when the result is already in the source*.
- If source has no metric: scope / ownership / complexity — **never invent** numbers (keep existing ban).
- Explicitly reject the external skills’ “add 35% ROI” style.

### 3. Action-verb diversity bank (from resume-tailor)

- Composer: short curated verb lists by theme (leadership / systems / product) — pick from bank, not only Built/Designed.
- Critic prompt: flag **mustFix/optionalImprove** when ≥3 bullets share the same opening verb (scanability).
- No code change to layout required.

### 4. Acronym dual-form for ATS (from ATS optimizers)

In job analyzer user/system guidance and/or keyword list post-process:

- When JD contains both forms (e.g. “CI/CD” + “continuous integration”), keep both in `atsKeywords`.
- When only an acronym appears, still list the acronym; **do not invent** expanded terms that never appear in the JD or skill bank.
- Composer: if source uses a tool full name and JD uses acronym, lightly mirror JD form **only when that token is already in source/approved skill name**.

### 5. “Changes made” changelog after critic revise (from tailored-generator “recommendations / changes”)

When pipeline runs a revision pass (`pipeline.py` revision=1):

- Write `selection-changelog.md` (or a section in `tailoring-strategy.md`) comparing pre/post selection:
  - added/removed achievement ids  
  - summary length delta  
  - highlight sourceId changes  
- Pure deterministic diff of TailorPayload reports — no LLM required.

### 6. Strengths line + intentional omissions (from tailored-generator post-draft advice)

In fit assessment or strategy markdown:

- **Competitive strengths**: 3 bullets built only from covered critical requirements + selected evidence (deterministic template: “covers X, Y, Z via selected work/projects”).
- **Intentional omissions**: already partially present; soft-link to keyword-coverage “missing” list with one sentence: “left off because not in verified catalog.”

### 7. Explicit ATS machine checklist (from ATS optimizer — deterministic)

Add a small `ats_checklist_markdown(resume_plain_text)` used when writing package artifacts:

- All-caps/standard section labels present (SUMMARY, EXPERIENCE, …)
- No “Tailored for…” footer
- Contact lacks raw `https://` noise (or cleaned)
- Length hint by line count (~not empty, not absurd)
- Keyword coverage % already computed — reference it

All rule-based; no third-party skill.

## Explicit non-goals

- Installing the three external skills into `.cursor/skills`
- Freeform Markdown resume generation in chat
- Prompt language that encourages fabricating metrics
- Industry career-change “functional resume” formats
- Power-verb spam / keyword stuffing

## Files to touch

| File | Change |
|---|---|
| [`cv/services/shared/cv_shared/package/prompts.py`](cv/services/shared/cv_shared/package/prompts.py) | Impact formula + verb diversity + acronym mirror (grounded) in composer; critic opener-verb note |
| [`cv/services/shared/cv_shared/package/reports.py`](cv/services/shared/cv_shared/package/reports.py) | Match table, strengths/omissions, ATS checklist helpers |
| [`cv/services/shared/cv_shared/package/pipeline.py`](cv/services/shared/cv_shared/package/pipeline.py) | Wire new markdown artifacts; selection changelog after revise |
| [`cv/services/shared/cv_shared/package/job_analyzer.py`](cv/services/shared/cv_shared/package/job_analyzer.py) | Light prompt/post-process for dual-form keywords when both appear in JD |
| [`cv/docs/RESUME_PIPELINE.md`](cv/docs/RESUME_PIPELINE.md) | Document mined report sections |

## Success criteria

1. Regenerated DevInfra package still uses same layout + verified sourceIds  
2. `fit-assessment.md` shows requirement×evidence table with honest gaps  
3. Composer output does not gain invented metrics  
4. After critic revision, changelog artifact appears when selection changes  
5. ATS checklist artifact is purely deterministic and reflects layout rules  
6. No new Cursor skills from composio/claude-office/paramchoudhary  

## Implementation order

1. Prompts (composer + critic + analyzer tweak)  
2. Reports (match table, strengths, ATS checklist)  
3. Pipeline wiring + changelog  
4. Docs smoke note  
