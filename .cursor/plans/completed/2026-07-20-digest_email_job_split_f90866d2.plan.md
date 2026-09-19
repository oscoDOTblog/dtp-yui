---
name: Digest email job split
overview: Split Gmail digests into per-listing jobs (sequential background ingest, Open URLs), and Telegram-alert when match recommendation is apply — same TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID pattern as osco-dot-blog.
todos:
  - id: digest-parser
    content: HTML digest listing extractor (company/title/location/link); no product cap; footer-link filtering only
    status: completed
  - id: deep-link-fetch
    content: Per-listing redirect resolve + best-effort JD fetch with card-text fallback
    status: completed
  - id: pipeline-wire
    content: Sequential per-listing loop (fetch→upsert→analyze); progress fields on ingest run doc
    status: completed
  - id: background-ingest
    content: Async POST /ingest/run + GET /ingest/status; single-flight lock; Inbox polls and stays browsable
    status: completed
  - id: persist-open-url
    content: Persist listing URL on every job; Open on Inbox + job detail
    status: completed
  - id: telegram-apply-alert
    content: Notify Telegram on recommendation=apply (SCORE_URGENT); osco env names; dedupe per job
    status: completed
  - id: ui-docs
    content: Compact live ingest banner + GMAIL_SETUP / .env.example Telegram note
    status: completed
isProject: false
---

# Split digest emails into per-listing jobs (background)

## Problem

Digest alerts list many roles in one message. Today [`message_to_raw_jobs`](cv/services/shared/cv_shared/intake/gmail_source.py):

- Caps at **5** links
- Reuses **one** subject-level title/company for every link
- Sets `descriptionText` to the **entire email body** for each job
- Only resolves redirects; does **not** fetch the listing page before analyze
- Manual **Run ingest** blocks the UI until the whole request finishes (job grid hidden)

## Target behavior

```mermaid
flowchart TD
  click[POST ingest/run]
  runDoc[cv_systemRuns ingest running]
  bg[Background sequential loop]
  upsert[Upsert each job]
  analyze[Analyze if eligible]
  poll[Inbox polls status + jobs]
  browse[User browses Open links]

  click --> runDoc --> bg
  bg --> upsert --> analyze
  upsert --> poll
  poll --> browse
```

- One Gmail digest → many `cv_jobs` (correct company/title/URL each)
- Process listings **sequentially** (no product cap; filter noise only)
- **Background ingest**: start returns immediately; work continues on the server
- Inbox stays usable: browse/Open already-ingested jobs while later listings are still scoring

## Approach

### 1. Digest listing extractor (HTML-first)

Extend [`gmail_source.py`](cv/services/shared/cv_shared/intake/gmail_source.py):

- Prefer HTML; extract listing cards (company, title, location, salary, job URL)
- Skip footer noise (unsubscribe, privacy, create alert, see more)
- Remove `links[:5]`; keep all valid listings after filtering
- Pathological guard only: **>100** candidates/message after filter → warn and stop that message
- Expand allowlist for glassdoor/indeed/linkedin job + tracking hosts

Fallback: one job per link with nearby title/company text if card parse fails.

### 2. Per-listing deep link enrich

- Resolve redirect → best-effort JD fetch (8s); else card snippet
- Persist `sourceUrl`, `canonicalApplyUrl`, `url` (prefer resolved), `fetchStatus`
- Never invent JD with LLM; never clear an existing URL on upsert refresh

### 3. Sequential pipeline + live progress

[`pipeline.py`](cv/services/shared/cv_shared/intake/pipeline.py):

- For each listing: enrich → normalize → upsert → analyze (if new + Bay Area eligible) → next
- After each listing, update the active ingest run document with progress:
  - `status`: `running` | `completed` | `failed`
  - `listingsTotal`, `listingsProcessed`, `jobsCreated`, `analyzed`, `outOfArea`, `currentTitle`, `errors[]`
- Distinct fingerprints; `discoveredBy` includes `messageId`, `subject`, `digestIndex`

### 4. Background ingest API (required)

Replace blocking `POST /ingest/run` behavior:

- **`POST /ingest/run?reprocess=`** — if an ingest is already `running`, return `409` with current run id; else create `cv_systemRuns` doc (`type: ingest`, `status: running`) and start work on a **daemon thread** in the API process (single Legion instance; no Redis). Return `{ runId, status: "running" }` immediately (~200).
- **`GET /ingest/status`** — latest ingest run (or by `runId`): progress fields above + `finishedAt` when done.
- Single-flight: only one ingest at a time (check Mongo for `status: running` before start; worker hourly path uses the same guard / same `run_ingest` entrypoint).
- Hourly worker continues to call `run_ingest` directly (already background relative to the UI).

### 5. Inbox UI — browse while ingesting

[`page.js`](cv/services/web/app/page.js):

- Run ingest / Reprocess: fire-and-forget start; do **not** hide the job grid
- Compact sticky/status banner (GIF + live text from `/ingest/status`, e.g. “Scoring 3/12 — Staff Full Stack @ Rippling”)
- Poll `/ingest/status` + `/jobs` every ~3s while `running`; stop when `completed`/`failed`
- **Open** on each card (`canonicalApplyUrl || url || sourceUrl`, new tab, stopPropagation)
- Job detail: prominent **Open** button (same URL order)
- Buttons disabled only while a run is `running` (prevent double-start); browsing/Open always allowed

### 6. Telegram alert on strong apply recommendation

Mirror [osco-dot-blog donate-contact](file:///Users/argo/Code/atos/osco-dot-blog-v2/src/app/api/donate-contact/route.js): `POST https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage` with `chat_id: TELEGRAM_CHAT_ID`.

**When:** after `analyze_job` produces `recommendation === "apply"` (score ≥ `SCORE_URGENT`, default **85** — same rule as the green APPLY badge in matching).

**Not when:** `consider`, `skip`, or `reject`.

**Message contents (plain text / HTML-safe):**
- Score + recommendation
- Title — Company
- Location / workMode
- Listing URL (Open target)
- Local job detail path hint (`/jobs/{id}`)
- One-line whyViable or top strong match if present

**Dedupe:** set `telegramNotifiedAt` on the match (or job) after a successful send; skip if already set so re-analyze / reprocess does not spam. Clear only if you later force-reanalyze with an explicit flag (not required for v1).

**Module:** new [`cv_shared/telegram.py`](cv/services/shared/cv_shared/telegram.py) using `httpx` (already in requirements). No-op log if env missing (same soft-fail as osco).

**Env** (document in [`.env.example`](cv/.env.example) — reuse osco values):

```bash
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

Pass through docker-compose for `api` + `worker`.

Hook call site: end of successful analyze inside the ingest loop (and manual Re-analyze on job detail if recommendation is apply and not yet notified).

### 7. Docs

[`GMAIL_SETUP.md`](cv/docs/GMAIL_SETUP.md) + README: digests split per listing; sequential background processing; Inbox browsable; Open uses stored URL; Telegram fires only for **apply** (≥85) using osco-style env vars.

## Defaults

| Setting | Value |
|---|---|
| Product max listings | None (all valid) |
| Pathological guard | 100 / message |
| Processing | Sequential, background thread |
| UI during ingest | Job list visible + poll |
| Fetch JD | Best-effort, 8s each |
| Single-flight | One ingest at a time |
| Telegram | Only `recommendation=apply`; soft-fail if unset |

## Out of scope

- Playwright for login-walled pages
- Redis/Celery / multi-replica job queue
- SSE/WebSockets (HTTP poll is enough)
- Telegram digests for `consider` band (roadmap Stage 3)
- Greenhouse/Lever watchlist (Stage 2B)

## Acceptance

- Digest with ~10–15 roles → that many jobs (not capped at 5)
- After clicking Run ingest, UI returns immediately; job cards appear/update as each listing finishes
- User can Open and view details for finished jobs while later ones are still analyzing
- Each job has a stored listing URL + working Open button
- Second Run ingest while one is running returns 409 / clear “already running” state
- Re-ingest does not duplicate; eligible jobs scored individually
- A job scored **apply** (≥85) sends one Telegram message; reprocess does not resend; missing Telegram env does not break ingest
