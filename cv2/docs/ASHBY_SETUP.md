# Ashby board setup

Operator guide for Ashby Job Postings API polling on the company watchlist.

## What this does

Hourly ingest (and **Poll** / **Poll all Ashby** on the Sources page) hits Ashby’s public Job Postings API for each enabled `ats: "ashby"` company in `cv_jobSources`, then runs the same normalize → Bay Area gate → upsert → auto-analyze path as Gmail and Greenhouse.

No Ashby API key is required. Board slugs are public path segments from careers pages.

## Public API

```bash
curl -sS 'https://api.ashbyhq.com/posting-api/job-board/{JOB_BOARD_NAME}?includeCompensation=true'
```

One response includes titles, locations, descriptions (`descriptionHtml` / `descriptionPlain`), apply URLs, and optional compensation. Unlike Greenhouse, there is no separate detail fetch.

## Finding a board slug

1. Open the company’s Ashby careers page, e.g. `https://jobs.ashbyhq.com/ashby`
2. The path segment after `/` is the **board slug** (`ashby`)
3. Confirm the API responds:

```bash
curl -sS 'https://api.ashbyhq.com/posting-api/job-board/ashby' | head -c 200
```

A JSON object with a `jobs` array means the slug is valid.

## Settings master toggle

1. Open **Settings** → **ATS board ingest**
2. Toggle **Ashby** on/off

| Control | Effect |
|---|---|
| Settings Ashby off | Skip all Ashby board polls |
| Settings on + company disabled | That board skipped |
| Settings on + company enabled | Board polled |

## Adding companies

### Sources UI

1. Open **Sources**
2. Set **ATS** to Ashby
3. Enter display name + board slug + optional location prefs
4. **Add** — API probes the public board before saving

### Seed file (bulk)

Add rows to [`seed/jobSources.json`](../seed/jobSources.json) with `"ats": "ashby"`, then:

```bash
curl -X POST 'http://localhost:8000/seed'
```

Example:

```json
{
  "_id": "src_ashby_ashby",
  "name": "Ashby",
  "ats": "ashby",
  "boardToken": "ashby",
  "priority": 80,
  "locations": ["San Francisco", "Bay Area", "Remote"],
  "enabled": true,
  "careersUrl": "https://jobs.ashbyhq.com/ashby"
}
```

## Polling

- **Poll** on a row → `POST /sources/{id}/poll` (Ashby-only run for that source)
- **Poll all Ashby** → `POST /ingest/run?sources=ashby`
- Hourly / **Run ingest** with `sources=all` includes Ashby after Greenhouse

## Manual Analyze URLs

Pasting `https://jobs.ashbyhq.com/{slug}/{jobId}` into Analyze uses the public board feed to resolve the posting (skip HTML scrape).

## Location + role gates

Same shared classifiers as Greenhouse / Gmail:

- [`config/location.json`](../config/location.json)
- [`config/roleFilter.json`](../config/roleFilter.json)

Ashby `isRemote` / `workplaceType` and `secondaryLocations` feed the location string / work-mode hint before gates run. Unlisted postings (`isListed: false`) are skipped on board poll.

## API cheatsheet

```bash
# Enable Ashby master toggle
curl -X PATCH 'http://localhost:8000/settings' \
  -H 'Content-Type: application/json' \
  -d '{"atsIngest":{"ashby":true}}'

# Create source
curl -X POST 'http://localhost:8000/sources' \
  -H 'Content-Type: application/json' \
  -d '{"name":"Ashby","boardToken":"ashby","ats":"ashby","locations":["Bay Area","Remote"]}'

# Poll one / all
curl -X POST 'http://localhost:8000/sources/src_ashby_ashby/poll'
curl -X POST 'http://localhost:8000/ingest/run?sources=ashby'
```
