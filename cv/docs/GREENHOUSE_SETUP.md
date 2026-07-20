# Greenhouse board setup (Stage 2B)

Operator guide for the Bay Area company watchlist and Greenhouse Job Board API polling.

## What this does

Hourly ingest (and **Poll** on the Sources page) hits the public Greenhouse boards API for each enabled company in `cv_jobSources`, then runs the same normalize → Bay Area gate → upsert → auto-analyze path as Gmail intake.

No Greenhouse API key is required. Board tokens are public slugs from career pages.

## Settings master toggle

1. Open **Settings** → **ATS board ingest**
2. Toggle **Greenhouse** on/off

When off, no Greenhouse HTTP polls run (hourly or Run ingest). Per-company switches on **Sources** still apply when the master is on.

| Control | Effect |
|---|---|
| Settings Greenhouse off | Skip all board polls |
| Settings on + company disabled | That board skipped |
| Settings on + company enabled | Board polled |

## Finding a board token

1. Open the company’s Greenhouse careers page, e.g. `https://boards.greenhouse.io/stripe`
2. The path segment after `/` is the **board token** (`stripe`)
3. Confirm the API responds:

```bash
curl -sS 'https://boards-api.greenhouse.io/v1/boards/stripe/jobs' | head -c 200
```

A JSON object with a `jobs` array means the token is valid.

## Adding companies

### Seed file (bulk)

Edit [`seed/jobSources.json`](../seed/jobSources.json), then:

```bash
curl -X POST 'http://localhost:8000/seed'
```

Identity fields (`name`, `boardToken`, `priority`, …) upsert without wiping `lastPolledAt` / errors. Operator-disabled sources stay disabled.

### Sources UI

1. Open **Sources**
2. Fill **Name**, **Board token**, optional **Priority**
3. **Add** — API probes the token before insert

## Polling

- **Poll** on a row → that board only (`POST /sources/{id}/poll`)
- **Poll all Greenhouse** → `POST /ingest/run?sources=greenhouse`
- Inbox **Run ingest** / hourly worker → Gmail then Greenhouse (`sources=all`)

Boards are polled sequentially with a short delay (~250ms). Failures set `lastError` on that source and do not abort the rest of the run.

## Verification checklist

1. Seed or add at least one valid board (e.g. Stripe)
2. Confirm Settings → Greenhouse is **on**
3. Click **Poll** (or wait for hourly ingest)
4. Confirm Sources shows `lastSuccessAt` and a job count
5. Open **Inbox** — Bay Area–eligible roles appear with source `greenhouse`; out-of-area roles land as Out of area and are not auto-analyzed
6. Turn Greenhouse **off** in Settings and poll again — no new board traffic; Sources may show the Settings banner

## API cheatsheet

```bash
# List watchlist
curl -sS http://localhost:8000/sources | jq '.[0:3]'

# Master toggle
curl -X PATCH http://localhost:8000/settings \
  -H 'Content-Type: application/json' \
  -d '{"atsIngest":{"greenhouse":true}}'

# Poll one source
curl -X POST 'http://localhost:8000/sources/src_greenhouse_stripe/poll'

# Greenhouse-only ingest
curl -X POST 'http://localhost:8000/ingest/run?sources=greenhouse'
```

## Security

- Public board API only — no credentials in `secrets/`
- Localhost-bound API/UI (same as the rest of CV)
- Do not commit private recruiter tokens or Harvest API keys (not used here)
