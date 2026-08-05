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

Highlights use the same grounding (`highlights: [{ sourceId, text }]`, max 6).

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
| [`cv_shared/resume/tailor.py`](../services/shared/cv_shared/resume/tailor.py) | Resume compose + verify + fallback |
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
