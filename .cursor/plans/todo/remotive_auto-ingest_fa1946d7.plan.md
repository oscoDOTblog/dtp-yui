---
name: Remotive auto-ingest
overview: Add an opt-in Remotive public API poller as a new auto-ingest source, gated by a Settings switch, reusing the existing Ashby-style fetch → normalize → upsert pipeline without a company watchlist.
todos:
  - id: adapter
    content: Add remotive_source.py (fetch, map raw, early prefilter, stats)
    status: completed
  - id: settings-backend
    content: Extend ATS_INGEST_KEYS + default remotive=false in settings.py
    status: completed
  - id: pipeline
    content: Wire remotive into run_ingest + skip enrich; update sources mode + API docstring
    status: completed
  - id: settings-ui
    content: Add Remote job APIs / Remotive Switch on settings page
    status: completed
  - id: docs
    content: Note Remotive in ARCHITECTURE.md; adjust ROADMAP deferred wording
    status: completed
isProject: false
---

# Remotive auto-ingest source

## Approach

Add Remotive as a **global API poller** (not a company watchlist row). Master toggle lives in Settings under a new **Remote job APIs** section; when on, hourly ingest + Inbox Fetch poll:

`GET https://remotive.com/api/remote-jobs?category=software-dev`

Maps into the existing normalize → location/role gates → upsert path used by Ashby. Default **off** (opt-in) because public results are ~24h delayed and Remotive terms restrict some commercial/signup-oriented reuse — supplementary only, not apply-immediately intake.

## Data flow

```mermaid
flowchart LR
  settings["Settings atsIngest.remotive"]
  worker["Worker / ingest run"]
  remotiveAPI["remotive.com/api/remote-jobs"]
  adapter["remotive_source.py"]
  pipeline["pipeline._ingest_raw_jobs"]
  jobs["cv_jobs"]

  settings --> worker
  worker --> adapter
  adapter --> remotiveAPI
  remotiveAPI --> adapter
  adapter --> pipeline
  pipeline --> jobs
```

## Backend

### 1. New adapter — [`cv/services/shared/cv_shared/intake/remotive_source.py`](cv/services/shared/cv_shared/intake/remotive_source.py)

Patterned on the single-shot Ashby path ([`ashby_source.py`](cv/services/shared/cv_shared/intake/ashby_source.py)):

| Field | Mapping |
|-------|---------|
| `externalId` | `remotive:{id}` |
| `source` | `remotive` |
| `title` / `company` | `title` / `company_name` |
| `location` | `candidate_required_location` (+ `"Remote"` if missing remote cue) |
| `workMode` | `"remote"` always (board is remote-only) |
| `descriptionRaw` / markdown | `description` via existing `description_fields_from_html_or_text` |
| `sourceUrl` / `url` | `url` |
| `postedAt` | `publication_date` |
| `discoveredBy` | `{ source: "remotive", category: "software-dev" }` |

Core functions:

- `fetch_remotive_jobs(category="software-dev")` — public GET, no key; polite `User-Agent`
- `remotive_job_to_raw(job)` — stable mapping above
- `early_keep_remotive_listing(...)` — title + location prefilter via `assess_location` / `assess_role_fit` + `ingest_drop_reason` (same idea as Ashby early filter; no board location prefs)
- `fetch_remotive_raw_jobs(app_settings=...)` — fetch → prefilter → raw list + stats

Fixed category: **`software-dev`** (matches the Remotive API example and role filter). No Sources-page watchlist.

Throttle: one API call per run (full list); respect `INGEST_MAX_LISTINGS` via pipeline truncation.

### 2. Settings — [`cv/services/shared/cv_shared/settings.py`](cv/services/shared/cv_shared/settings.py)

```python
ATS_INGEST_KEYS = ("greenhouse", "ashby", "remotive")
DEFAULT_ATS_INGEST = {
    "greenhouse": True,
    "ashby": True,
    "remotive": False,  # opt-in supplementary source
}
```

`_normalize_ats_ingest` / `is_ats_source_enabled("remotive")` pick this up automatically.

### 3. Pipeline — [`cv/services/shared/cv_shared/intake/pipeline.py`](cv/services/shared/cv_shared/intake/pipeline.py)

- Accept `sources` mode `"remotive"` (alongside `all`, `gmail`, `greenhouse`, `ashby`, `manual`)
- After Ashby block: if `run_remotive` and `is_ats_source_enabled("remotive")` → `fetch_remotive_raw_jobs` → `_ingest_raw_jobs(..., count_prefix="remotive")`
- Skip listing-page enrich for Remotive (JD already in API payload):
  - extend `if src in ("greenhouse", "ashby")` → include `"remotive"` (two call sites ~346 and ~584)
- Summary counters: `remotiveJobsListed`, `remotiveJobsPrefiltered`, `remotiveJobsCreated/Updated`

### 4. API docs string — [`cv/services/api/main.py`](cv/services/api/main.py)

Update `/ingest/run` docstring: `sources=remotive` allowed. No new endpoint needed; worker already runs `sources=all`.

## Frontend

### Settings UI — [`cv/services/web/app/settings/page.js`](cv/services/web/app/settings/page.js)

Add a **Remote job APIs** section (separate from “ATS board ingest” so it is clear Remotive is not on the Sources watchlist):

- Switch key: `atsIngest.remotive` (reuse existing `toggleAts("remotive")` / `apiPatch`)
- Label: **Remotive**
- Description: public remote-jobs API, category `software-dev`; ~24h delayed; supplementary; governed by Remotive terms

Default hydrate: `{ greenhouse: true, ashby: true, remotive: false }` so missing API field does not flash as on.

No Sources page changes.

## Docs

Light touch only:

- [`cv/docs/ARCHITECTURE.md`](cv/docs/ARCHITECTURE.md) — one paragraph: Remotive poll when `atsIngest.remotive` is true
- [`cv/docs/ROADMAP.md`](cv/docs/ROADMAP.md) — rephrase deferred item to “Remotive as *primary* intake” (implemented as opt-in supplementary)

## Tests (optional, small)

If the repo has pure adapter tests nearby: `remotive_job_to_raw` unit test for externalId / workMode / company mapping from a fixture dict. Otherwise skip to keep the change tight.

## Out of scope

- Storing or redistributing full JD outside existing private `cv_jobs` / personal copilot flow
- Extra categories, search query, or Settings category picker (hardcode `software-dev`)
- Remotive under Apply Copilot agent / Glassdoor `agent.json`
- Per-company `cv_jobSources` rows
- Changing location gates (remote already eligible via `assess_location` “remote always eligible”)
