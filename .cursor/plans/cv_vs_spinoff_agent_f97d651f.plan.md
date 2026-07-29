---
name: CV vs spinoff agent
overview: Keep the hybrid job-application browser agent inside dtp-yui’s CV product as Stage 6 (a new long-running service), not a separate repo—reuse scoring, packages, and tracking via the existing FastAPI, and start with MVP 0 (apply-assist on a known job) rather than Glassdoor search automation.
todos:
  - id: agent-service-scaffold
    content: Add cv/services/agent Compose service (Node + Playwright, persistent profile) that calls FastAPI for job/package/status
    status: pending
  - id: state-machine-events
    content: Implement application state machine + Mongo event log + WebSocket/SSE feed to web UI
    status: pending
  - id: mvp0-ats-adapters
    content: "MVP 0: Greenhouse + Lever + generic fill; pause before submit; human approve + confirmation"
    status: pending
  - id: dashboard-copilot-panels
    content: "Extend job/Applications UI: current state, activity feed, input queue, pause/approve/take-control controls"
    status: pending
  - id: docs-stage6
    content: Update ROADMAP/ARCHITECTURE/COLLECTIONS for Stage 6 apply runner boundaries
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

- Job intake + dedupe (Gmail, Greenhouse, Ashby, Analyze queue)
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
Existing CV brain (reuse)          New Stage 6 service
┌─────────────────────┐            ┌──────────────────────────┐
│ FastAPI + worker    │◄──HTTP───►│ Apply runner (Playwright) │
│ matching / packages │            │ state machine + events   │
│ cv_jobs / status    │            │ ATS adapters + policy    │
└──────────┬──────────┘            └──────────┬───────────────┘
           │                                  │
           └──────── MongoDB + Next.js ───────┘
                     (extend Applications / job detail)
```

## Concrete placement

| Piece | Where |
|---|---|
| Runner process | New `cv/services/agent/` (Compose service), not inside `api` or `worker` |
| Browser stack | Node + Playwright first (matches [`travel/`](travel/) pattern); add Stagehand only when generic ATS pages need `observe`/`act` |
| Brain | Keep Python: call existing `GET /jobs/{id}`, generate package, patch application status |
| Live UI | Extend [`cv/services/web`](cv/services/web) — job detail + Applications: activity feed, input queue, pause/approve controls |
| Persistence | Reuse `cv_jobs` / packages; add `cv_applicationRuns` + `cv_applicationEvents` (camelCase) for runner state |
| Discovery | **Do not** rebuild Glassdoor search as primary intake for MVP |

## MVP scope (aligned with your “MVP 0”)

Ship **Application Copilot**, not the Glassdoor search runner:

1. User picks a scored job in the existing UI (or Analyze URL already in `cv_jobs`).
2. Package generates via existing pipeline (or reuse latest package).
3. Agent opens `canonicalApplyUrl` / apply URL in headed Chromium (persistent profile).
4. Detect Greenhouse / Lever / generic; fill Level A fields; upload resume; queue Level B/C.
5. Emit structured events to the dashboard; stop at **AWAITING_REVIEW**.
6. Human approves submit; agent confirms via page/URL signals; updates `applicationStatus`.

Defer for later stages: Glassdoor/LinkedIn search automation, Workday adapter, Gmail confirmation matching, auto-submit, vision/coordinate fallbacks.

This matches roadmap constraints and avoids ToS/volume risk on Glassdoor while validating the hardest path (ATS fill + human gate).

## Stack note (resolve the TS vs Python tension)

The writeup recommends TypeScript + Stagehand + Ollama scoring in the agent. **Do not reimplement scoring or doc gen in the agent.**

- **CV brain stays Python** (already production for you).
- **Browser runner is Node + Playwright** in-repo (Stagehand as a dependency when the generic adapter needs it).
- Prefer **Browser Use only if** you insist on one language; otherwise Stagehand’s hybrid model fits the adapter strategy better and mirrors your travel Playwright habit.

## Security / policy (product rules, not afterthoughts)

Encode in the runner from day one:

- Allowed actions only (navigate/click/type approved/upload approved docs).
- Never treat page text as system instructions.
- Level C fields → always ask user or use saved confirmed answers.
- No CAPTCHA bypass; pause for manual solve.
- No LinkedIn automation (already deferred).

## Docs / roadmap update when implementing

When you build it: mark Stage 6 in progress in [`ROADMAP.md`](cv/docs/ROADMAP.md), add an “Apply runner” section to [`ARCHITECTURE.md`](cv/docs/ARCHITECTURE.md), and document collections in [`COLLECTIONS.md`](cv/docs/COLLECTIONS.md).

## Success criterion (first milestone)

From a job already in Inbox: open apply URL → fill one Greenhouse or Lever form to the review screen → structured event log in the dashboard → human-approved submit with confirmation signal → `applicationStatus` updated. No search automation required.
