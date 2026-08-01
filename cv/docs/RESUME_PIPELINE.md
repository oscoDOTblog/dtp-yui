# Resume tailor + render pipeline

Content (career evidence) is separated from design (PDF/DOCX templates).

## Flow

```text
cv_workHistory / cv_projects / cv_skills
        ↓
achievement catalog (work:{id}:b{i}, project:{id}:b{i})
        ↓
Ollama select + rewrite (sourceId required) → TailorPayload
        ↓
verify (drop unknown ids, employer invent check, page caps)
        ↓
resume.yaml + selection-report.json + gaps.md
        ↓
PDF: RenderCV (if settings.resume.renderEngine=rendercv) or legacy ReportLab
DOCX: structured python-docx from the same payload
```

## Achievement IDs

| Pattern | Source |
|---|---|
| `work:{workHistoryId}:b{index}` | `cv_workHistory.bullets[i]` |
| `project:{projectId}:b{index}` | `cv_projects.resumeBullets[i]` (or `summary` if no bullets) |

The model must never invent an achievement without a catalog `sourceId`. Verification drops unknown IDs and reverts unsafe rewrites to the original statement.

## Settings

`cv_settings.resume`:

| Field | Values | Default |
|---|---|---|
| `renderEngine` | `legacy` \| `rendercv` | `legacy` |
| `templateId` | RenderCV theme name | `classic` |
| `pages` | `1` \| `2` | `2` |

Ollama think flag: `ollama.thinkByProcess.resumeTailor` (only when the call uses Ollama).

Document LLM provider: `documentProvider.provider` (`ollama` | `openai`) — cover letter + resume tailor. OpenAI key in `secrets/openai-api-key`.

Toggle render engine and document provider in the web Settings page. Rebuild the API image after adding `rendercv[full]` so the CLI is available inside the container.

## Package artifacts

Under `generated-applications/{company}-{role}/`:

- `resume.pdf` / `resume.docx` / `resume.txt`
- `resume.yaml` — RenderCV input (always written)
- `selection-report.json` — chosen ids, rewrites, omitted requirements, renderer used
- `gaps.md` — match gaps + omitted JD requirements

## Code map

| Module | Role |
|---|---|
| [`cv_shared/resume/achievements.py`](../services/shared/cv_shared/resume/achievements.py) | Catalog builder |
| [`cv_shared/resume/tailor.py`](../services/shared/cv_shared/resume/tailor.py) | Ollama + verify + fallback |
| [`cv_shared/resume/render_rendercv.py`](../services/shared/cv_shared/resume/render_rendercv.py) | YAML + CLI PDF |
| [`cv_shared/resume/render_docx.py`](../services/shared/cv_shared/resume/render_docx.py) | Structured DOCX |
| [`cv_shared/resume/legacy.py`](../services/shared/cv_shared/resume/legacy.py) | ReportLab fallback |
| [`cv_shared/documents.py`](../services/shared/cv_shared/documents.py) | Package orchestration |

## Switching to RenderCV

1. Ensure API image installs `rendercv[full]` (see `services/api/requirements.txt`).
2. Settings → **Use RenderCV for PDF**.
3. Generate a package; confirm `selection-report.json` has `"renderer": "rendercv"`.
4. If RenderCV fails, the package still ships with `"renderer": "legacy_fallback"`.
