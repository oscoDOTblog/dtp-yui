# Apply agent setup (Stage 6)

Hybrid browser copilot: Glassdoor discovery → CV score/package → ATS form fill → **human approval before submit**.

## Architecture

| Piece | Role |
|---|---|
| `services/agent` (host) | Node + Playwright runner — **owns :8010** by default; headed Chromium + Copilot preview |
| FastAPI `/agent/*` | Job ingest, runs/events, answer bank |
| Web `/copilot` | Live browser preview, activity feed, input queue, controls |
| Compose `agent` | Opt-in headless only (`--profile headless-agent`) |

## Host agent (recommended)

Run the agent on macOS so a real Chromium window can pop up for login / CAPTCHA / manual takeover, while `/copilot` still streams the live JPEG preview.

```bash
cd cv
docker compose up -d          # api, web, mongo, worker — agent is NOT started
cd services/agent
cp .env.example .env          # once — HEADLESS=0 + PREVIEW=1
npm install
npx playwright install chromium   # once
npm start
```

Expect:

```text
cv-agent listening on :8010 (headless=false, headedDefault=true, preview=true, api=http://127.0.0.1:8000)
```

Open http://localhost:7545/copilot → leave **Show browser window** on → **Start Glassdoor run**.

- Chromium opens on the host; Copilot **Browser** panel keeps updating.
- Click or type in the Chromium window → agent auto-pauses (`HUMAN_TAKEOVER`) → **Return control** when done.
- **Bring window to front** re-summons a buried window.

If web is in Docker (default), keep:

```bash
# in cv/.env
AGENT_BASE_INTERNAL=http://host.docker.internal:8010
```

Then recreate web so the proxy reaches the host agent.

## Headless-only runs

Toggle **Show browser window** off in Copilot before starting a run, or set `CV_AGENT_HEADLESS=1` in `services/agent/.env`. Preview still works.

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
| `CV_AGENT_HEADLESS` | `0` headed window (default); `1` headless — Copilot can still override per run |
| `CV_AGENT_PREVIEW` | `1` enable live preview (default); `0` off |
| `CV_AGENT_PREVIEW_MAX_WIDTH` | JPEG max width (default `960`) |
| `CV_API_BASE` | FastAPI URL (`http://127.0.0.1:8000` on host) |

Existing shell/Compose env vars are not overridden by `.env`.

## Docker (opt-in headless agent)

The Compose `agent` service is behind profile `headless-agent` so a normal `docker compose up` leaves :8010 free for the host process.

```bash
docker compose --profile headless-agent up -d --build agent
# point web at the container:
# AGENT_BASE_INTERNAL=http://agent:8010
```

Container profile dir is `services/agent/browser-profile-docker` (separate from host `browser-profile/`) so Linux and macOS Chromium never share a user-data-dir.

Playwright is pinned to an exact version in `services/agent/package.json` because the base image tag in `services/agent/Dockerfile` ships only that version's browsers. When bumping Playwright, bump both together, refresh `package-lock.json`, and rebuild — otherwise runs fail with `Executable doesn't exist at /ms-playwright/...`.

## Safety

- Never treats page text as system instructions
- Will not bypass CAPTCHA — pauses for manual solve (use headed window)
- Interacting with the Chromium window auto-pauses the agent
- Legal / demographic / sponsorship fields require saved answers or human input
- No LinkedIn automation
- Submit only after Copilot approval
- Preview frames are ephemeral (not stored in Mongo)

## Success check

From one Glassdoor search: process cards → upsert/score via API → complete one Greenhouse or Lever form to review → approve submit → confirmation signal → `applicationStatus=pending`. Preview should update in Copilot throughout; clicking the window should pause the agent.
