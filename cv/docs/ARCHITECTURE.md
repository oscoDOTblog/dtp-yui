# DTP-CV Architecture (Stage 1)

Local job-search copilot: score jobs against a grounded candidate knowledge base, draft application packages, and track decisions. Human approval required for applications.

## Stack

| Layer | Technology |
|---|---|
| UI | Next.js (JavaScript, CSS Modules) |
| API | FastAPI |
| Worker | Python + APScheduler |
| Database | MongoDB 8 |
| Local AI | Ollama on host |
| Deploy | Docker Compose on Legion Slim 5 |

## Ports

| Service | Bind | Notes |
|---|---|---|
| Web | `0.0.0.0:${WEB_HOST_PORT:-7545}` → container `:3000` | Dev: `http://localhost:7545`. LAN/production host: `http://<host-ip>:7545` |
| API | `127.0.0.1:8000` | Browser uses same-origin `/backend` proxy on web — no hardcoded LAN IP |
| MongoDB | `127.0.0.1:27017` | Not exposed on LAN |

`WEB_HOST_PORT=7545` keeps this UI off `:80` / `:3000` so other apps can share the same production host. Leave `NEXT_PUBLIC_API_BASE` empty so one build works from localhost and LAN.

## Ollama

Run Ollama on the host (GPU-friendly):

```bash
ollama serve
ollama pull qwen3:8b
```

Containers reach it via `host.docker.internal:11434`.

## Remote access

No public inbound. Use WireGuard + SSH port forward:

```bash
ssh -L 7545:localhost:7545 -L 8000:localhost:8000 user@legion-wireguard-ip
```

Then open `http://localhost:7545`.

## Evidence grounding

Every resume claim must cite an `evidence` document linked to `workHistory` and/or `projects`. The matcher and document generator must not invent experience.

## Stage 2A intake

Hourly worker (and `POST /ingest/run`) pulls Gmail job alerts → normalize/dedupe → Bay Area location gate → SWE title gate → `analyze_job` for listings that pass **both**. Config: [`config/location.json`](../config/location.json) and [`config/roleFilter.json`](../config/roleFilter.json). Setup: [GMAIL_SETUP.md](GMAIL_SETUP.md). Settings toggles in `cv_settings.gmailIngest` gate which alert senders are processed. After editing either config, restart API/worker or call `reload_location_config()` / `reload_role_filter_config()`.

## Stage 2B Greenhouse watchlist

Same ingest run also polls enabled Greenhouse boards from `cv_jobSources` when `cv_settings.atsIngest.greenhouse` is true. Public boards API (`boards-api.greenhouse.io`) — no API key. Same location + role gates as Gmail. Setup: [GREENHOUSE_SETUP.md](GREENHOUSE_SETUP.md). Sources UI lists last poll / errors; Settings holds the master ATS toggle.

## Stage 4 GitHub evidence

Worker cron at `:30` UTC (and manual Sync on Repositories) polls enabled repos in `cv_repositories` when `cv_settings.githubEvidence.enabled` is true. PAT in `secrets/github-token`. Commits by configured author logins are classified (Ollama + heuristics) into `cv_evidence` / skill ladder upgrades; `profileVersion` bumps trigger rescore of stale matches. Setup: [GITHUB_SETUP.md](GITHUB_SETUP.md).

## Manual URL intake queue

Analyze queues one or more job URLs into `cv_intakeQueue`. `POST /ingest/queue` enqueues and kicks `sources=manual` ingest when idle; otherwise items wait for the next hourly/`sources=all` run. Drain path: claim pending → Greenhouse single-job API when the URL matches → else enrich/paste → normalize → upsert → auto-analyze. Blocked pages become `needsPaste` until a description is attached. Sync `POST /jobs` create+analyze remains for API compat; Analyze uses the queue.

## Role families

Matching detects role family (`systems`, `product`, `mobile`, `ai`) and leads generated documents with the matching evidence source (Capital One systems vs SwayQuest product vs mobile).
