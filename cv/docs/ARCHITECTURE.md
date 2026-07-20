# CV Architecture (Stage 1)

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

## Ports (localhost only)

| Service | Bind |
|---|---|
| Web | `127.0.0.1:3000` |
| API | `127.0.0.1:8000` |
| MongoDB | `127.0.0.1:27017` |

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
ssh -L 3000:localhost:3000 -L 8000:localhost:8000 user@legion-wireguard-ip
```

Then open `http://localhost:3000`.

## Evidence grounding

Every resume claim must cite an `evidence` document linked to `workHistory` and/or `projects`. The matcher and document generator must not invent experience.

## Stage 2A intake

Hourly worker (and `POST /ingest/run`) pulls Gmail job alerts → normalize/dedupe → Bay Area location gate → `analyze_job` for eligible listings. Config: `config/location.json`. Setup: [GMAIL_SETUP.md](GMAIL_SETUP.md). Settings toggles in `cv_settings.gmailIngest` gate which alert senders are processed.

## Stage 2B Greenhouse watchlist

Same ingest run also polls enabled Greenhouse boards from `cv_jobSources` when `cv_settings.atsIngest.greenhouse` is true. Public boards API (`boards-api.greenhouse.io`) — no API key. Setup: [GREENHOUSE_SETUP.md](GREENHOUSE_SETUP.md). Sources UI lists last poll / errors; Settings holds the master ATS toggle.

## Role families

Matching detects role family (`systems`, `product`, `mobile`, `ai`) and leads generated documents with the matching evidence source (Capital One systems vs SwayQuest product vs mobile).
