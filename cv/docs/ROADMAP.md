# Roadmap

## Stage 1 — Candidate profile + manual job URLs *(done)*

- Seeded knowledge base (skills, projects, work history, evidence)
- Paste job URL or description
- Ollama extraction + weighted match + meaningful gaps + gap insights
- Generate application package (docx/pdf/md)
- Local Next.js dashboard (Inbox, Analyze, Gaps, Applications, Profile)
- Docker Compose on Legion

## Stage 2A — Email intake + foundation *(current)*

- Shared `JobSource` intake: normalize, fingerprint, dedupe → `cv_jobs`
- Bay Area location / work-arrangement classifier (hard gate before auto-analyze)
- Gmail job-alert ingestion (LinkedIn, Indeed, Built In, Wellfound, Google Jobs, etc.)
- Hourly worker ingest + `POST /ingest/run`
- Inbox source + location chips
- Setup guide: [GMAIL_SETUP.md](GMAIL_SETUP.md)

## Stage 2B — Bay Area company watchlist + Greenhouse

- Curated company list in `cv_jobSources` (board tokens, priority, locations)
- Greenhouse Job Board API polling
- Same normalizer → location gate → upsert → analyze
- Simple Sources UI (last poll / errors)

## Stage 2C — Lever (+ Ashby if watchlist needs it)

- Lever Postings API adapter (same interface as Greenhouse)
- Add Ashby only if enough priority companies use it

## Stage 3 — Logistics scoring + notify

- Commute tiers from Oakland (config, not live transit APIs)
- Reweight match score with work-arrangement + commute
- Digest notifications (Gmail / Telegram): urgent ≥85, digest 70–84

## Stage 4 — GitHub evidence engine

- Cron at `:30` — poll configured repos; skip unchanged commit SHA
- Evidence ladder: mentioned → installed → implemented → substantial → tested → deployed → maintained
- Update skills/projects; rescore open jobs when profile version bumps
- `repository-cache/` for shallow clones when needed

## Stage 5 — Application tracker

- Full pipeline: Discovered → Recommended → Interested → Drafted → Ready → Applied → Interview → Rejected/Offer
- Learn from `userDecisions`
- Nightly cleanup of expired listings + DB backup

## Stage 6 — Browser assistance (non-LinkedIn ATS)

- Playwright Level 3: fill external ATS, pause before submit
- Explicitly **no** LinkedIn Easy Apply automation or scraping
- Optional: user-triggered form-fill assist

## Explicitly deferred

- LinkedIn browser automation / scraping
- Mass remote APIs (Remotive, etc.) as primary intake
- USAJOBS unless opted in
- Live commute APIs
- Fully autonomous submission without human review
