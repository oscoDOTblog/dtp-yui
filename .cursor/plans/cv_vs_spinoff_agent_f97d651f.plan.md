---
name: CV vs spinoff agent
overview: Keep the hybrid job-application browser agent inside dtp-yui’s CV product as Stage 6 (a new long-running service). MVP entry is Glassdoor (saved search / results inbox); DTP-CV Inbox becomes an upstream first step later. Reuse scoring, packages, and tracking via existing FastAPI; pause before submit.
todos:
  - id: agent-service-scaffold
    content: Add cv/services/agent Compose service (Node + Playwright, persistent profile) that calls FastAPI for upsert/score/package/status
    status: pending
  - id: glassdoor-inbox-runner
    content: "MVP entry: open Glassdoor with persistent profile, run one saved search, iterate result cards, extract + fingerprint via CV API"
    status: pending
  - id: state-machine-events
    content: Implement application state machine (start SEARCHING on Glassdoor) + Mongo event log + WebSocket/SSE feed to web UI
    status: pending
  - id: mvp0-ats-adapters
    content: "Greenhouse + Lever + generic fill after Apply redirect; pause before submit; human approve + confirmation"
    status: pending
  - id: dashboard-copilot-panels
    content: "Copilot panels: current Glassdoor job, activity feed, input queue, pause/approve/take-control (CV Inbox entry deferred)"
    status: pending
  - id: docs-stage6
    content: Update ROADMAP/ARCHITECTURE/COLLECTIONS for Stage 6 apply runner + Glassdoor-first flow
    status: pending
isProject: false
---

# Keep the apply agent inside CV (not a spinoff)

## Verdict

**Stay in [dtp-yui/cv](cv/) as Stage 6.** Do not create a separate product repo for the MVP.

This feature is already named on the roadmap ([`cv/docs/ROADMAP.md`](cv/docs/ROADMAP.md) Stage 6: Playwright fill of external ATS, pause before submit; no LinkedIn; no autonomous submit). The proposed design is that stage, expanded with a live decision feed and human-in-the-loop controls.

A spinoff only makes sense later if you want to sell a generic “form filler” to people who do not use your evidence-grounded CV pipeline. For personal use on Legion, a second codebase would duplicate the hard parts you already have.

## Why not a spinoff

Existing CV already owns the differentiated product surface:

- Job intake + dedupe (Gmail, Greenhouse, Ashby, Analyze queue) — still used for upsert/score when the agent discovers listings
- Evidence-grounded scoring ([`cv_shared/matching.py`](cv/services/shared/cv_shared/matching.py))
- Tailored packages (PDF/DOCX/txt + selection report)
- Application status on `cv_jobs`
- Same MongoDB, Ollama, Docker Compose, dashboard

The browser layer is greenfield (~30–40% of the work), but it is valuable *because* it consumes those packages and scores. Forking would force either API coupling across repos or a rewrite of scoring/docs.

## Why not “just more FastAPI handlers”

The agent is a **different runtime** from the API:

- Long-lived headed Chromium + persistent profile
- Pause for user input / take-control
- Checkpoints and crash resume
- WebSocket event stream to the dashboard

So: **same product, new service**, not more routes inside the request/response API process.

```text
Glassdoor (MVP entry)          Existing CV brain              Apply runner
┌──────────────────┐           ┌─────────────────────┐       ┌──────────────────────────┐
│ Saved search /   │──extract─►│ FastAPI upsert/score│◄─────►│ Playwright + state machine│
│ results “inbox”  │           │ packages / status   │       │ ATS adapters + policy    │
└──────────────────┘           └──────────┬──────────┘       └──────────┬───────────────┘
                                          │                              │
                                          └────── MongoDB + Next.js ─────┘
                                                (live copilot dashboard)
```

**Later (deferred):** DTP-CV Inbox becomes the **first step** of a run (pick/queue jobs or kick a search from Inbox UI). Until then, the runner starts on Glassdoor directly.

## Concrete placement

| Piece | Where |
|---|---|
| Runner process | New `cv/services/agent/` (Compose service), not inside `api` or `worker` |
| Browser stack | Node + Playwright first (matches [`travel/`](travel/) pattern); add Stagehand when generic ATS pages need `observe`/`act` |
| Brain | Keep Python: upsert discovered jobs, score, generate package, patch application status |
| Live UI | Copilot dashboard panels (activity feed, input queue, controls); wire “start from CV Inbox” later |
| Persistence | Reuse `cv_jobs` / packages; add `cv_applicationRuns` + `cv_applicationEvents` (camelCase); optional `search_run` metadata |
| Discovery (MVP) | **Glassdoor saved search / results inbox** as the run entry; human-scale rates; stop on CAPTCHA/challenge |

## MVP flow (Glassdoor-first)

Entry state: **SEARCHING** on Glassdoor (not “user picked a job in CV Inbox”).

1. Launch headed Chromium with a dedicated persistent profile (Glassdoor login preserved).
2. Open one configured saved search (query / location / filters from agent config).
3. Iterate visible result cards (cap e.g. 10 per run): open listing → extract title/company/location/salary/description/apply URL.
4. Fingerprint + upsert into `cv_jobs` via FastAPI (reuse existing normalize/dedupe); score via existing matcher.
5. Skip duplicates / already applied / below threshold; for APPLY decisions, generate package via existing pipeline.
6. Click Apply → classify ATS (Greenhouse / Lever / generic) → fill Level A; upload resume; queue Level B/C unknowns.
7. Emit structured events to the dashboard; stop at **AWAITING_REVIEW**.
8. Human approves submit; confirm via page/URL signals; update `applicationStatus`; return to Glassdoor results tab (preserve pagination); next card.
9. Stop after configured `maxApplicationsPerRun` / runtime limits.

```text
GLASSDOOR_SEARCHING
  → JOB_EXTRACTED → DUPLICATE_CHECKED → SCORED
  → DOCUMENTS_GENERATING → APPLICATION_STARTED → FORM_FILLING
  → AWAITING_REVIEW → SUBMITTING → SUBMISSION_CONFIRMED
  → RETURNING_TO_RESULTS
```

### Deferred (explicit)

- **CV Inbox as first step** — start/queue runs from the existing Inbox UI; Glassdoor becomes step 2
- LinkedIn automation
- Workday adapter, vision/coordinate fallbacks
- Gmail confirmation matching
- Auto-submit without human approval
- High-volume scraping / CAPTCHA bypass

Glassdoor stays a **discovery surface** at human pace: logged-in session, no parallel scrape, pause when challenged, always follow through to the employer ATS when possible.

## Stack note (resolve the TS vs Python tension)

Do **not** reimplement scoring or doc gen in the agent.

- **CV brain stays Python** (already production for you).
- **Browser runner is Node + Playwright** in-repo (Stagehand when the generic adapter needs it).
- Prefer **Browser Use only if** you insist on one language; otherwise Stagehand’s hybrid model fits the adapter strategy better.

## Security / policy (product rules, not afterthoughts)

Encode in the runner from day one:

- Allowed actions only (navigate/click/type approved/upload approved docs).
- Never treat page text as system instructions.
- Level C fields → always ask user or use saved confirmed answers.
- No CAPTCHA bypass; pause for manual solve.
- No LinkedIn automation (already deferred).

## Docs / roadmap update when implementing

When you build it: mark Stage 6 in progress in [`ROADMAP.md`](cv/docs/ROADMAP.md), add an “Apply runner” section to [`ARCHITECTURE.md`](cv/docs/ARCHITECTURE.md) (Glassdoor-first entry; Inbox-first later), and document collections in [`COLLECTIONS.md`](cv/docs/COLLECTIONS.md).

## Success criterion (first milestone)

From one configured Glassdoor saved search: process up to ten result cards, upsert/score via CV API, correctly skip duplicates, complete **one** Greenhouse or Lever application to the review screen with a structured event log, human-approved submit with confirmation signal, then return to Glassdoor results for the next card.
