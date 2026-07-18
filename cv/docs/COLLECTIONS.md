# MongoDB Collections

**Database:** `DTP` (set via `MONGO_DB`)

All CV collections are prefixed with **`cv_`** so they sit alongside other DTP data in the same database.

Field names use **camelCase**.

## Stage 1 (active)

| Collection | Purpose |
|---|---|
| `cv_candidates` | Primary profile: identity, contact, education, preferences, positioning |
| `cv_workHistory` | Employer roles (Capital One ladder) with dated bullets |
| `cv_skills` | Skill bank with evidenceLevel / approvedForResume |
| `cv_projects` | Independent/portfolio project buckets |
| `cv_evidence` | Grounded claims linked to skills / projects / workHistory |
| `cv_jobs` | Discovered or manually pasted listings |
| `cv_jobMatches` | Score, recommendation, strongMatches, meaningfulGaps |
| `cv_applicationPackages` | Paths under `generated-applications/` |
| `cv_applications` | Pipeline status (`discovered` → `drafted`, …) |
| `cv_documents` | Metadata for generated resume/cover letter files |
| `cv_userDecisions` | apply / save / reject / draft |
| `cv_systemRuns` | Seed and analyze run logs |

Evidence levels: `mentioned` | `installed` | `implemented` | `substantial` | `tested` | `deployed` | `maintained`

## Stage 2+ (stub names)

- `cv_jobSources` — LinkedIn email alerts, ATS feeds
- `cv_gmailMessages` — processed Gmail message ids
- `cv_repositories` — GitHub repo scan state
- `cv_repositoryScans` — per-commit analysis records

Constants live in [`services/shared/cv_shared/collections.py`](../services/shared/cv_shared/collections.py).
