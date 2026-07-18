# Roadmap

## Stage 1 — Candidate profile + manual job URLs (current)

- Seeded knowledge base (skills, projects, work history, evidence)
- Paste job URL or description
- Ollama extraction + weighted match + meaningful gaps
- Generate application package (docx/pdf/md)
- Local Next.js dashboard
- Docker Compose on Legion

## Stage 2 — LinkedIn alert email ingestion

- Gmail API OAuth (Desktop client); tokens in `secrets/`
- Worker cron at `:00` — search LinkedIn job-alert emails
- Extract jobs, content-hash dedupe, store processed message ids
- Optional Gmail label `AI Job Agent/Processed`
- Auto-analyze; Telegram notify (urgent ≥85, digest 70–84, archive below 70)

## Stage 3 — GitHub evidence engine

- Cron at `:30` — poll configured repos; skip unchanged commit SHA
- Evidence ladder: mentioned → installed → implemented → substantial → tested → deployed → maintained
- Update skills/projects; rescore open jobs when profile version bumps
- `repository-cache/` for shallow clones when needed

## Stage 4 — Application tracker

- Full pipeline: Discovered → Recommended → Interested → Drafted → Ready → Applied → Interview → Rejected/Offer
- Learn from `user_decisions`
- Nightly cleanup of expired listings + DB backup

## Stage 5 — Browser assistance (non-LinkedIn ATS)

- Playwright Level 3: fill external ATS, pause before submit
- Explicitly **no** LinkedIn Easy Apply automation or scraping
- Optional: user-triggered form-fill assist

## Out of scope permanently (or until explicitly reconsidered)

- LinkedIn scraping / autonomous Easy Apply
- Fully autonomous submission without human review
