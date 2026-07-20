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
| `cv_systemRuns` | Seed, analyze, and ingest run logs |
| `cv_gapInsights` | Aggregated recurring gaps/warnings across analyses (ranked by `totalSeen`) |

Evidence levels: `mentioned` | `installed` | `implemented` | `substantial` | `tested` | `deployed` | `maintained`

### `cv_gapInsights`

One document per normalized requirement. Upserted on each successful job analyze (counts once per `jobId`). Status: `open` | `learning` | `resolved`.

### `cv_jobs` intake fields (Stage 2A+)

| Field | Purpose |
|---|---|
| `externalId` | Stable id from source, e.g. `gmail:msgId:linkHash` or `greenhouse:token:123` |
| `source` | `manual` \| `gmail` \| `greenhouse` \| `lever` \| … |
| `sourceUrl` | URL as discovered |
| `canonicalApplyUrl` | Prefer company ATS URL after redirect resolve |
| `discoveredBy` | `{ source, alertName?, alertLocation?, messageId? }` |
| `locationAssessment` | Classifier output (see below) |
| `firstSeenAt` / `lastSeenAt` | Intake timestamps |
| `fingerprints.exact` / `fingerprints.fuzzy` | Dedup keys |
| `contentHash` | Hash of description text (legacy + still used) |
| `status` | Includes `out_of_area` when Bay Area gate fails |

### `locationAssessment`

```json
{
  "workArrangement": "hybrid",
  "geographicEligibility": "bay_area",
  "officeCities": ["San Francisco"],
  "bayAreaEligible": true,
  "confidence": 0.9,
  "evidence": ["location mentions San Francisco"]
}
```

## Stage 2A (active)

| Collection | Purpose |
|---|---|
| `cv_gmailMessages` | Processed Gmail message ids (idempotent ingest) |
| `cv_jobSources` | Configured sources (email query + future ATS boards) |

## Stage 2B+ / later stubs

- `cv_repositories` — GitHub repo scan state
- `cv_repositoryScans` — per-commit analysis records

Constants live in [`services/shared/cv_shared/collections.py`](../services/shared/cv_shared/collections.py).
