# Resume tailor + render pipeline

Content (career evidence) is separated from design (PDF/DOCX templates).

## Flow

### Simple path (Ollama / OpenAI off)

```text
cv_workHistory / cv_projects / cv_skills
        ↓
achievement catalog (work:{id}:b{i}, project:{id}:b{i})
        ↓
LLM select + rewrite (sourceId required) → TailorPayload
        ↓
verify (drop unknown ids, employer invent check, page caps)
        ↓
finalize (project floor, skill ceiling ~24, milestone highlights, header fields)
        ↓
layout model (employer consolidation + dual skills)
        ↓
cover letter (one LLM call, shared selected evidence when available)
        ↓
resume.yaml + selection-report.json + gaps.md
        ↓
PDF: RenderCV (if settings.resume.renderEngine=rendercv) or legacy ReportLab
DOCX: structured python-docx from the same payload
```

### OpenAI multi-stage path (`documentProvider.provider=openai` + API key)

```text
catalog + match + job
        ↓
1. Job Analyzer      → job-analysis.json
2. Evidence Ranker   → evidence-ranking.json
3. Resume Composer   → TailorPayload (verified)
4. Resume Critic     → scores; optional one revise pass
5. Cover Letter      → grounded on selected achievements
6. Consistency Review → safe cover letter
        ↓
artifacts: ats-keywords.md, fit-assessment.md,
         interview-talking-points.md, tailoring-strategy.md,
         application-report.json
        ↓
render (same DOCX / PDF path)
```

Stage process names for OpenAI usage / Ollama think fallbacks:
`jobAnalyzer`, `evidenceRanker`, `resumeTailor`, `resumeCritic`, `coverLetter`, `consistencyReview`.

On any multi-stage orchestrator failure the package falls back to the simple tailor + cover path.

## Achievement IDs

| Pattern | Source |
|---|---|
| `work:{workHistoryId}:b{index}` | `cv_workHistory.bullets[i]` |
| `project:{projectId}:b{index}` | `cv_projects.resumeBullets[i]` (or `summary` if no bullets) |

The model must never invent an achievement without a catalog `sourceId`. Verification drops unknown IDs and reverts unsafe rewrites to the original statement.

Highlights use the same grounding (`highlights: [{ sourceId, text }]`, max 6). Deterministic post-verify may replace thin tool-list highlights with **career milestones** (e.g. multi-level promotions, independent product span) using synthetic `milestone:n` ids; employers and facts still come only from work history / selected evidence.

## Resume layout (shared `layout.py`)

All render paths (plain text, DOCX, RenderCV) go through `cv_shared/resume/layout.py` so structure stays aligned:

| Behavior | Detail |
|---|---|
| Employer consolidation | Work bullets grouped by company; stacked titles newest-first (`YYYY–YYYY`); shared bullets under one Capital One block |
| Independent section | `INDEPENDENT SOFTWARE ENGINEER` + period/location; project subheads + selected project bullets |
| Header | Name → `professionalTitle` (or `targetRole`) → `specialtyLine` → cleaned contact (`linkedin.com/...`, no `https://`) |
| Section labels | SUMMARY → SELECTED HIGHLIGHTS → CORE EXPERTISE → EXPERIENCE → independent → TECHNOLOGIES → EDUCATION |
| Skills dual display | **CORE EXPERTISE**: flat ` • `-joined names; **TECHNOLOGIES**: category lines from approved skills |
| Footer | No “Tailored for…” line on rendered artifacts (metadata stays in selection-report) |

Two-page packages enforce a **project floor** (~4 project bullets / ≥2 projects when catalog has projects) so independent work is not dropped for DevInfra-heavy ranking. Skill selection ceiling is ~24 approved ids.

## Settings

`cv_settings.resume`:

| Field | Values | Default |
|---|---|---|
| `renderEngine` | `legacy` \| `rendercv` | `legacy` |
| `templateId` | RenderCV theme name | `classic` |
| `pages` | `1` \| `2` | `2` |

Ollama think flags: `ollama.thinkByProcess.*` for each document process (only when the call uses Ollama).

Document LLM provider: `documentProvider.provider` (`ollama` | `openai`) — routes all package document processes listed above when OpenAI is selected. OpenAI key in `secrets/openai-api-key`.

Toggle render engine and document provider in the web Settings page. Rebuild the API image after adding `rendercv[full]` so the CLI is available inside the container.

## Background generate (navigation-safe)

`POST /jobs/{jobId}/generate` starts a `cv_systemRuns` row (`type: generatePackage`) and returns immediately. The package is built on a daemon thread; poll `GET /jobs/{jobId}/generate` until `status` is `completed` or `failed`. One running generate per job. See `cv_shared/package_runs.py`.

## Cover letter voice

Cover letters are full business letters (date, Hiring Team / company, salutation, Thank you / Sincerely), not resume-bullet prose. The composer uses narrative motivation + elevated career themes grounded in selected achievements and the JD; it must not inventory tools or paste bullets. See `cv_shared/package/prompts.py` (`COVER_LETTER_SYSTEM`) and `cover_letter.py`. Consistency review must not strip first-person personality when claims stay grounded.

## Package artifacts

Under `generated-applications/{company}-{role}/`:

- `resume.pdf` / `resume.docx` / `resume.txt`
- `resume.yaml` — RenderCV input (always written)
- `selection-report.json` — chosen ids, rewrites, omitted requirements, `pipeline`, stage providers
- `gaps.md` — match gaps + omitted JD requirements
- `cover-letter.pdf` / `.docx` / `.txt`
- Multi-stage only: `job-analysis.json`, `evidence-ranking.json`, `ats-keywords.md`, `fit-assessment.md`, `interview-talking-points.md`, `tailoring-strategy.md`, `application-report.json`

## Code map

| Module | Role |
|---|---|
| [`cv_shared/resume/achievements.py`](../services/shared/cv_shared/resume/achievements.py) | Catalog builder |
| [`cv_shared/resume/tailor.py`](../services/shared/cv_shared/resume/tailor.py) | Resume compose + verify + project floor + milestones |
| [`cv_shared/resume/layout.py`](../services/shared/cv_shared/resume/layout.py) | Employer grouping, independent section, dual skills display |
| [`cv_shared/package/`](../services/shared/cv_shared/package/) | OpenAI multi-stage orchestrator + stage modules |
| [`cv_shared/package/pipeline.py`](../services/shared/cv_shared/package/pipeline.py) | Stage sequencing |
| [`cv_shared/resume/render_rendercv.py`](../services/shared/cv_shared/resume/render_rendercv.py) | YAML + CLI PDF |
| [`cv_shared/resume/render_docx.py`](../services/shared/cv_shared/resume/render_docx.py) | Structured DOCX |
| [`cv_shared/resume/legacy.py`](../services/shared/cv_shared/resume/legacy.py) | ReportLab fallback |
| [`cv_shared/documents.py`](../services/shared/cv_shared/documents.py) | Package orchestration |

## Switching to RenderCV

1. Ensure API image installs `rendercv[full]` (see `services/api/requirements.txt`).
2. Settings → **Use RenderCV for PDF**.
3. Generate a package; confirm `selection-report.json` has `"renderer": "rendercv"`.
4. If RenderCV fails, the package still ships with `"renderer": "legacy_fallback"`.
