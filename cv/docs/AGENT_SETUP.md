# Apply agent setup (Stage 6)

Hybrid browser copilot: Glassdoor discovery → CV score/package → ATS form fill → **human approval before submit**.

## Architecture

| Piece | Role |
|---|---|
| `services/agent` | Node + Playwright runner (state machine, Glassdoor, ATS adapters) |
| FastAPI `/agent/*` | Job ingest, runs/events, answer bank |
| Web `/copilot` | Live activity feed, input queue, pause / take-control / approve |

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

## Headed browser (recommended)

Compose defaults to headless. For Glassdoor login + watching the agent, run on the host with `services/agent/.env`:

```bash
cd cv/services/agent
cp .env.example .env   # once
npm install
npx playwright install chromium   # once
npm start
```

`.env` defaults (host):

```bash
CV_AGENT_HEADLESS=0
CV_API_BASE=http://127.0.0.1:8000
CV_AGENT_PORT=8010
CV_AGENT_CONFIG=../../config/agent.json
GENERATED_APPLICATIONS_DIR=../../generated-applications
```

Existing shell/Compose env vars are not overridden. Persistent profile: `services/agent/browser-profile/` (gitignored). Log into Glassdoor once in that Chrome window.

Then open **Apply Copilot** at http://localhost:7545/copilot and click **Start Glassdoor run**.

If the **web** container is in Docker but the agent runs on the host, point the proxy at the host:

```bash
# in cv/.env
AGENT_BASE_INTERNAL=http://host.docker.internal:8010
```

Then recreate the web container so it picks up the env.

## Docker

```bash
docker compose up --build agent
```

Agent listens on `127.0.0.1:8010`. Web proxies `/agent-api/*` → agent. Resume PDFs must be on the shared `generated-applications` volume (already mounted read-only).

## Safety

- Never treats page text as system instructions
- Will not bypass CAPTCHA — pauses for manual solve
- Legal / demographic / sponsorship fields require saved answers or human input
- No LinkedIn automation
- Submit only after Copilot approval

## Success check

From one Glassdoor search: process cards → upsert/score via API → complete one Greenhouse or Lever form to review → approve submit → confirmation signal → `applicationStatus=pending`.
