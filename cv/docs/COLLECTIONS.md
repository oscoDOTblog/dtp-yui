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
| `cv_userDecisions` | Application track updates (`apply` → `round4`, `rejected`) |
| `cv_systemRuns` | Seed, analyze, and ingest run logs |
| `cv_gapInsights` | Aggregated recurring gaps/warnings across analyses (ranked by `totalSeen`) |

Evidence levels: `mentioned` | `installed` | `implemented` | `substantial` | `tested` | `deployed` | `maintained`

### `cv_gapInsights`

One document per normalized requirement. Upserted on each successful job analyze (counts once per `jobId`). Status: `open` | `learning` | `resolved`.

### `cv_jobs` intake fields (Stage 2A+)

| Field | Purpose |
|---|---|
| `externalId` | Stable id from source, e.g. `gmail:msgId:linkHash`, `greenhouse:token:123`, or `ashby:slug:uuid` |
| `source` | `manual` \| `gmail` \| `greenhouse` \| `ashby` \| `lever` \| … |
| `sourceUrl` | URL as discovered |
| `canonicalApplyUrl` | Prefer company ATS URL after redirect resolve |
| `discoveredBy` | `{ source, alertName?, alertLocation?, messageId? }` |
| `locationAssessment` | Classifier output (see below) |
| `roleAssessment` | SWE title gate output (see below) |
| `firstSeenAt` / `lastSeenAt` | Intake timestamps |
| `fingerprints.exact` / `fingerprints.fuzzy` | Dedup keys |
| `contentHash` | Hash of description text (legacy + still used) |
| `descriptionRaw` | Plain-text job description (matching, documents, hashing) |
| `descriptionMarkdown` | Readable markdown for UI render (from structured HTML at intake); fall back to `descriptionRaw` when absent |
| `status` | Intake: `new` \| `out_of_area` \| `wrong_role`; soft pipeline mirrors (`interested`, `saved`, `interview`, `rejected`) |
| `applicationStatus` | Human track: `apply` \| `pending` \| `round1`–`round4` \| `rejected` |
| `applicationStatusAt` | When `applicationStatus` was last set |
| `fitOverrides` | Map of normalized requirement → `strong` \| `warning` \| `gap` (user fit assessment); applied on score + Re-analyze |
| `fitOverridesUpdatedAt` | When a fit override was last saved |

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

Policy (shared by Gmail + Greenhouse): hybrid/onsite need a `bayAreaCities` match from [`config/location.json`](../config/location.json); **remote is always eligible** unless the listing excludes California. After editing the config, restart API/worker or call `reload_location_config()`.

### `roleAssessment`

```json
{
  "roleEligible": true,
  "matchedIncludes": ["software engineer"],
  "matchedExcludes": [],
  "confidence": 0.9,
  "evidence": ["title matches software engineer"]
}
```

Policy (shared intake): title allowlist / blocklist from [`config/roleFilter.json`](../config/roleFilter.json). Blocklist wins; ambiguous titles like bare `Engineer` may use description patterns. Failures set `status: wrong_role` and skip auto-analyze. After editing, restart API/worker or call `reload_role_filter_config()`.

## Stage 2A / 2B (active)

| Collection | Purpose |
|---|---|
| `cv_gmailMessages` | Processed Gmail message ids (idempotent ingest) |
| `cv_settings` | App settings (UI source of truth). Doc `_id: "app"` with `gmailIngest`, `atsIngest`, and `githubEvidence` master toggles |
| `cv_jobSources` | ATS company watchlist (Greenhouse boards) |
| `cv_intakeQueue` | Manual job URLs queued from Analyze for intake digestion |

### `cv_settings`

```json
{
  "_id": "app",
  "gmailIngest": {
    "enabled": true,
    "linkedinEmail": true,
    "indeedEmail": true,
    "glassdoorEmail": true,
    "builtinEmail": true,
    "otherEmail": true
  },
  "atsIngest": {
    "greenhouse": true,
    "ashby": true
  },
  "githubEvidence": {
    "enabled": true,
    "authorLogins": ["oscoDOTblog"],
    "defaultLookback": "7d",
    "discoverRepos": true
  },
  "ollama": {
    "think": false,
    "thinkByProcess": {
      "jobExtract": false,
      "profileUpdate": false,
      "githubClassify": false,
      "coverLetter": false,
      "resumeTailor": false
    }
  },
  "resume": {
    "renderEngine": "legacy",
    "templateId": "classic",
    "pages": 2
  },
  "updatedAt": "ISO-8601"
}
```

`resume.renderEngine`: `legacy` (ReportLab) or `rendercv`. See [RESUME_PIPELINE.md](RESUME_PIPELINE.md).
### `cv_jobSources`

| Field | Purpose |
|---|---|
| `_id` | e.g. `src_greenhouse_stripe` or `src_ashby_ashby` |
| `name` | Display company name |
| `ats` | `greenhouse` \| `ashby` (Lever later) |
| `boardToken` | Public board slug (Greenhouse token or Ashby jobs page name) |
| `priority` | Poll order (higher first) |
| `locations` | Preferred / hint locations |
| `enabled` | Per-company poll switch (also requires Settings `atsIngest.{ats}`) |
| `careersUrl` | Board careers URL |
| `lastPolledAt` / `lastSuccessAt` | Poll timestamps |
| `lastError` | Last poll error string (cleared on success) |
| `lastJobCount` | Jobs returned on last successful poll |
| `createdAt` / `updatedAt` | Audit timestamps |

Seeded from [`seed/jobSources.json`](../seed/jobSources.json). Identity fields upsert on seed without wiping poll state or re-enabling disabled sources.

### `cv_intakeQueue`

Manual URL intake queue (Analyze page). Drained only by `run_ingest` when `sources` is `manual` (analyze lane). Inbox `sources=all` does not touch this queue.

```json
{
  "_id": "iq_…",
  "url": "https://…",
  "descriptionRaw": null,
  "status": "pending",
  "error": null,
  "jobId": null,
  "fetchStatus": null,
  "createdAt": "ISO-8601",
  "updatedAt": "ISO-8601",
  "processedAt": null
}
```

Statuses: `pending` → `processing` → `done` | `failed` | `needsPaste`. Enqueue dedupes against existing `pending`/`processing` rows with the same URL.

## Stage 4 — GitHub evidence

| Collection | Purpose |
|---|---|
| `cv_repositories` | Configured GitHub repos + scan state |
| `cv_repositoryScans` | Per-commit analysis records |

### `cv_repositories`

| Field | Purpose |
|---|---|
| `_id` | e.g. `repo_sway_f4` (matches `projects.repositoryIds`) |
| `fullName` | `owner/repo` |
| `defaultBranch` | Branch to scan (default `main`) |
| `projectIds` | Linked projects |
| `enabled` | Per-repo switch (also requires Settings `githubEvidence.enabled`) |
| `lastSeenCommitSha` | HEAD SHA after last successful scan |
| `lastScannedAt` / `lastSuccessAt` | Scan timestamps |
| `lastError` | Last error string (cleared on success) |
| `lastCommitCount` | Commits processed on last success |
| `clonePath` | Relative path under `repository-cache/` when cloned |
| `suggested` | Found by repo discovery; awaiting approval (excluded from scans) |
| `dismissed` | Operator dismissed the suggestion (never re-suggested) |
| `discoveredAt` | When discovery found the repo |

Seeded from [`seed/repositories.json`](../seed/repositories.json). Identity upsert preserves scan state.

### `cv_repositoryScans`

| Field | Purpose |
|---|---|
| `_id` | `{repositoryId}:{sha}` |
| `repositoryId` | Parent repo |
| `sha` / `committedAt` / `message` / `files` | Commit metadata |
| `extracted` | Classifier output (skills / levels / claims) |
| `createdAt` | When analyzed |

Constants live in [`services/shared/cv_shared/collections.py`](../services/shared/cv_shared/collections.py).

## Stage 2C+ / later stubs

_(none currently — Stage 4 collections are active)_
