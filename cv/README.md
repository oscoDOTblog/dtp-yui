# CV Job Copilot

Local AI job-search copilot with **human approval**. Score jobs against a grounded candidate knowledge base, generate tailored application packages, and track decisions.

Stage **2B** adds a Greenhouse company watchlist on top of Stage 2A Gmail intake. See [docs/ROADMAP.md](docs/ROADMAP.md).

## Prerequisites

- Docker + Docker Compose
- [Ollama](https://ollama.com) on the host with a model pulled:

```bash
ollama serve
ollama pull qwen3:8b
```

## Quick start

```bash
cd cv
cp .env.example .env
docker compose up --build
```

### MongoDB Atlas

Set in `.env`:

```bash
MONGO_DB=DTP
MONGO_URI=mongodb+srv://USER:PASSWORD@CLUSTER.mongodb.net/DTP?retryWrites=true&w=majority
```

You can omit the local `mongodb` Compose service when using Atlas. Data is stored in database **`DTP`** in collections prefixed with **`cv_`** (e.g. `cv_candidates`, `cv_jobs`, `cv_skills`).

Open:

- Web: http://localhost:3000
- API: http://localhost:8000/health
- API docs: http://localhost:8000/docs

The worker auto-seeds MongoDB from `seed/` on first start (profile + Greenhouse watchlist).

## Gmail job-alert intake (Stage 2A)

Follow the full guide: **[docs/GMAIL_SETUP.md](docs/GMAIL_SETUP.md)**

Short version:

1. Put `gmail-client-secret.json` in `secrets/`
2. Run `PYTHONPATH=services/shared python scripts/gmail_auth.py`
3. Label alerts with `JobAlerts`
4. `curl -X POST http://localhost:8000/ingest/run` (background; poll `/ingest/status`) or wait for the hourly worker

## Greenhouse company watchlist (Stage 2B)

Follow: **[docs/GREENHOUSE_SETUP.md](docs/GREENHOUSE_SETUP.md)**

Short version:

1. Seed loads `seed/jobSources.json` into `cv_jobSources` (or add companies on **Sources**)
2. Enable **Greenhouse** under Settings → ATS board ingest
3. **Poll** on Sources, or `curl -X POST 'http://localhost:8000/ingest/run?sources=greenhouse'`

## Workflow

1. Open **Analyze** and paste a job description (URL fetch is best-effort; LinkedIn usually blocks), **or** let Gmail / Greenhouse ingest fill the Inbox.
2. Review score, strong evidence, and meaningful gaps.
3. Check **Gaps** for recurring missing requirements ranked by frequency (mark Learning / Resolved as you close them).
4. Click **Generate documents** → files land in `generated-applications/{company}-{role}/`.
5. Open the listing yourself and submit (Level 1 automation).

## Seed data

| File | Contents |
|---|---|
| `seed/candidates.json` | Identity, education, preferences, positioning |
| `seed/workHistory.json` | Capital One roles + systems/infra bullets |
| `seed/skills.json` | Portfolio + Capital One skills bank |
| `seed/projects.json` | SwayQuest / DTP project buckets |
| `seed/evidence.json` | Grounded claims linked to skills/work/projects |
| `seed/jobSources.json` | Greenhouse company watchlist (board tokens) |

Force reseed (profile replace + watchlist identity upsert):

```bash
curl -X POST 'http://localhost:8000/seed?force=true'
```

Job sources also upsert on a normal `POST /seed` even when the candidate is already present.

## Remote access (WireGuard + SSH)

```bash
ssh -L 3000:localhost:3000 -L 8000:localhost:8000 user@legion-wireguard-ip
```

## Docs

- [ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [COLLECTIONS.md](docs/COLLECTIONS.md)
- [ROADMAP.md](docs/ROADMAP.md)
- [GMAIL_SETUP.md](docs/GMAIL_SETUP.md) — Gmail inbox + OAuth for job alerts
- [GREENHOUSE_SETUP.md](docs/GREENHOUSE_SETUP.md) — company watchlist + board tokens

## Current scope

In: profile seed, manual job paste, Gmail digest → per-listing ingest (background), Greenhouse board watchlist + Sources UI, Settings toggles for Gmail senders and ATS (`cv_settings`), Bay Area location gate, Ollama match, Telegram on apply (≥85), gap insights, document generation, dashboard, Docker Compose.

Out: Lever/Ashby (2C), Telegram digests for consider-band, GitHub evidence polling, Playwright ATS (see roadmap).
