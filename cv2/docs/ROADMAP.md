# Roadmap

## Stage 1 — Candidate profile + manual job URLs *(done)*

- Seeded knowledge base (skills, projects, work history, evidence)
- Paste job URL or description (Analyze → intake queue; see below)
- Ollama extraction + weighted match + meaningful gaps + gap insights
- Generate application package (docx/pdf/md)
- Local Next.js dashboard (Inbox, Analyze, Gaps, Applications, Profile)
- Docker Compose on Legion

### Manual URL intake queue *(Analyze)*

- Multi-URL paste into `cv_intakeQueue`; process immediately on the Analyze lane if idle (independent of Inbox Fetch)
- Shared normalize → Bay Area gate → upsert → auto-analyze path
- Greenhouse single-job URLs use boards API (dedupe with watchlist polls)
- Blocked pages → `needsPaste` until description attached
- APIs: `POST/GET/PATCH/DELETE /ingest/queue`, `POST /ingest/queue/process`

## Stage 2A — Email intake + foundation *(done)*

- Shared `JobSource` intake: normalize, fingerprint, dedupe → `cv_jobs`
- Bay Area location / work-arrangement classifier (hard gate before auto-analyze)
- Gmail job-alert ingestion (LinkedIn, Indeed, Built In, Wellfound, Google Jobs, etc.)
- Hourly worker ingest + `POST /ingest/run`
- Inbox source + location chips
- Settings toggles for Gmail alert senders
- Setup guide: [GMAIL_SETUP.md](GMAIL_SETUP.md)

## Stage 2B — Bay Area company watchlist + Greenhouse *(done)*

- Curated company list in `cv_jobSources` (board tokens, priority, locations)
- Greenhouse Job Board API polling
- Same normalizer → location gate → upsert → analyze
- Settings master toggle (`atsIngest.greenhouse`)
- Sources UI (last poll / errors / per-company enable)
- Setup guide: [GREENHOUSE_SETUP.md](GREENHOUSE_SETUP.md)

## Stage 2C — Ashby *(done)* + Lever

- Ashby public Job Postings API adapter (same watchlist + gates as Greenhouse)
- Settings master toggle (`atsIngest.ashby`)
- Sources UI ATS selector + Poll all Ashby
- Setup guide: [ASHBY_SETUP.md](ASHBY_SETUP.md)
- Lever Postings API adapter still pending

## Stage 3 — Logistics scoring + notify

- Commute tiers from Oakland (config, not live transit APIs)
- Reweight match score with work-arrangement + commute
- Digest notifications (Gmail / Telegram): apply ≥70, consider 50–69, reject &lt;50

## Stage 4 — GitHub evidence engine *(current)*

- Cron at `:30` — poll configured repos; skip unchanged commit SHA
- Manual Sync with lookback presets (`1d` … `all`) on Repositories page
- Evidence ladder: mentioned → installed → implemented → substantial → tested → deployed → maintained
- Update skills/projects; rescore open jobs when profile version bumps
- `repository-cache/` for shallow clones when needed
- Setup guide: [GITHUB_SETUP.md](GITHUB_SETUP.md)

## Stage 4.5 — Resume tailor + RenderCV

- Achievement catalog from work/project bullets (`work:` / `project:` sourceIds)
- Ollama select+rewrite with Pydantic verification (no invented claims)
- `selection-report.json` + `gaps.md` beside each package
- PDF via RenderCV behind `cv_settings.resume.renderEngine` (default `legacy`)
- Structured DOCX from the same tailor payload
- Guide: [RESUME_PIPELINE.md](RESUME_PIPELINE.md)

## Stage 5 — Application tracker

- Full pipeline: Discovered → Recommended → Interested → Drafted → Ready → Applied → Interview → Rejected/Offer
- Learn from `userDecisions`
- Nightly cleanup of expired listings + DB backup

## Stage 6 — Browser assistance (non-LinkedIn ATS) *(in progress)*

- Playwright apply agent (`cv/services/agent`) — Glassdoor-first discovery
- Upsert/score/package via existing FastAPI; Greenhouse + Lever + generic form fill
- Live Apply Copilot dashboard (`/copilot`) with activity feed + human pause before submit
- Explicitly **no** LinkedIn Easy Apply automation or scraping
- Deferred: CV Inbox as run entry (Glassdoor becomes step 2), Workday adapter, auto-submit

## Explicitly deferred

- LinkedIn browser automation / scraping
- Mass remote APIs (Remotive, etc.) as primary intake (Remotive is available opt-in as supplementary only)
- USAJOBS unless opted in
- Live commute APIs
- Fully autonomous submission without human review
- CV Inbox as first step of an agent run (Glassdoor is MVP entry)