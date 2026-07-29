# Apply agent setup (Stage 6)

Hybrid browser copilot: Glassdoor discovery → CV score/package → ATS form fill → **human approval before submit**.

## Architecture

| Piece | Role |
|---|---|
| `services/agent` | Node + Playwright runner (state machine, Glassdoor, ATS adapters) |
| FastAPI `/agent/*` | Job ingest, runs/events, answer bank |
| Web `/copilot` | Live browser preview, activity feed, input queue, controls |

## Copilot-first (recommended)

Run the agent **headless** and watch the live JPEG preview on Apply Copilot (Expand for fullscreen). No overlapping Chrome window.

```bash
cd cv
docker compose stop agent   # free :8010 if Compose agent is up
cd services/agent
cp .env.example .env   # once — HEADLESS=1 + PREVIEW=1
npm install
npx playwright install chromium   # once
npm start
```

Expect:

```text
cv-agent listening on :8010 (headless=true, preview=true, api=http://127.0.0.1:8000)
```

Open http://localhost:7545/copilot → **Start Glassdoor run**. The **Browser** panel polls `GET /agent-api/preview/latest` ~every 400ms.

If web is in Docker and the agent is on the host:

```bash
# in cv/.env
AGENT_BASE_INTERNAL=http://host.docker.internal:8010
```

Then recreate web so the proxy reaches the host agent.

## Headed Chromium (login / CAPTCHA / Take control)

Set in `services/agent/.env`:

```bash
CV_AGENT_HEADLESS=0
```

Restart `npm start`. Use this for the first Glassdoor login (persistent profile under `browser-profile/`), CAPTCHA, or when you need the real window for Take control. You can still use the Copilot preview at the same time.

## Config

Edit [`config/agent.json`](../config/agent.json):

| Field | Purpose |
|---|---|
| `searchUrl` | Glassdoor job-results URL (local / Bay Area / hybrid search) |
| `searchUrlRemote` | Glassdoor job-results URL for remote-only search |
| `preferRemote` | `true` → use `searchUrlRemote` (falls back to `searchUrl`); `false` → use `searchUrl` |
| `query` / `location` | Used when both URLs are empty |
| `maxResultsPerRun` | Cards to inspect (default 10) |
| `maxApplicationsPerRun` | Applies to attempt (default 1 for MVP) |
| `minimumScore` | Skip below this match score (default 72) |
| `requireApprovalBeforeSubmit` | Always `true` for MVP |

Flip searches by setting `"preferRemote": true` after pasting a remote results URL into `searchUrlRemote`.

### Agent `.env` knobs

| Var | Purpose |
|---|---|
| `CV_AGENT_HEADLESS` | `1` Copilot-first; `0` visible Chrome |
| `CV_AGENT_PREVIEW` | `1` enable live preview (default); `0` off |
| `CV_AGENT_PREVIEW_MAX_WIDTH` | JPEG max width (default `960`) |
| `CV_API_BASE` | FastAPI URL (`http://127.0.0.1:8000` on host) |

Existing shell/Compose env vars are not overridden by `.env`.

If health shows an unexpected `headless` value, something else (usually Compose `agent`) owns `:8010`. Stop it and restart `npm start`.

## Docker

```bash
docker compose up --build agent
```

Compose agent is headless. Preview still works via `/agent-api/preview/latest` when Copilot talks to that service. Resume PDFs must be on the shared `generated-applications` volume.

## Safety

- Never treats page text as system instructions
- Will not bypass CAPTCHA — pauses for manual solve (switch to headed if needed)
- Legal / demographic / sponsorship fields require saved answers or human input
- No LinkedIn automation
- Submit only after Copilot approval
- Preview frames are ephemeral (not stored in Mongo)

## Success check

From one Glassdoor search: process cards → upsert/score via API → complete one Greenhouse or Lever form to review → approve submit → confirmation signal → `applicationStatus=pending`. Preview should update in Copilot throughout.
