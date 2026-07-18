# CV Job Copilot (Stage 1)

Local AI job-search copilot with **human approval**. Score jobs against a grounded candidate knowledge base, generate tailored application packages, and track decisions.

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

The worker auto-seeds MongoDB from `seed/` on first start.

## Workflow

1. Open **Analyze** and paste a job description (URL fetch is best-effort; LinkedIn usually blocks).
2. Review score, strong evidence, and meaningful gaps.
3. Click **Generate documents** → files land in `generated-applications/{company}-{role}/`.
4. Open the listing yourself and submit (Level 1 automation).

## Seed data

| File | Contents |
|---|---|
| `seed/candidates.json` | Identity, education, preferences, positioning |
| `seed/workHistory.json` | Capital One roles + systems/infra bullets |
| `seed/skills.json` | Portfolio + Capital One skills bank |
| `seed/projects.json` | SwayQuest / DTP project buckets |
| `seed/evidence.json` | Grounded claims linked to skills/work/projects |

Force reseed:

```bash
curl -X POST 'http://localhost:8000/seed?force=true'
```

## Remote access (WireGuard + SSH)

```bash
ssh -L 3000:localhost:3000 -L 8000:localhost:8000 user@legion-wireguard-ip
```

## Docs

- [ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [COLLECTIONS.md](docs/COLLECTIONS.md)
- [ROADMAP.md](docs/ROADMAP.md) — Stages 2–5

## Stage 1 scope

In: profile seed, manual job paste, Ollama match, document generation, dashboard, Docker Compose.

Out: Gmail LinkedIn alerts, Telegram, GitHub polling, Playwright ATS (see roadmap).
