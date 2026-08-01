# DTP-CV Architecture (Stage 1)

Local job-search copilot: score jobs against a grounded candidate knowledge base, draft application packages, and track decisions. Human approval required for applications.

## Stack

| Layer | Technology |
|---|---|
| UI | Next.js (JavaScript, Tailwind v4 + coss) |
| API | FastAPI |
| Worker | Python + APScheduler |
| Apply agent | Node + Playwright (Stage 6) |
| Database | MongoDB 8 |
| Local AI | Ollama on host (default for all LLM calls) |
| Optional cloud AI | OpenAI Chat Completions for cover letter + resume tailor |
| Deploy | Docker Compose on Legion Slim 5 |

## Ports

| Service | Bind | Notes |
|---|---|---|
| Web | `0.0.0.0:${WEB_HOST_PORT:-7545}` → container `:3000` | Dev: `http://localhost:7545`. LAN/production host: `http://<host-ip>:7545` |
| API | `127.0.0.1:8000` | Browser uses same-origin `/backend` proxy on web — no hardcoded LAN IP |
| Agent | `127.0.0.1:8010` | Browser uses `/agent-api` proxy; headed runs often on host |
| MongoDB | `127.0.0.1:27017` | Not exposed on LAN |

`WEB_HOST_PORT=7545` keeps this UI off `:80` / `:3000` so other apps can share the same production host. Leave `NEXT_PUBLIC_API_BASE` empty so one build works from localhost and LAN.

## Ollama

Run Ollama on the host (GPU-friendly):

```bash
ollama serve
ollama pull qwen3:8b
```

Containers reach it via `host.docker.internal:11434`.

### Document generation provider

Cover letters and resume tailor go through `cv_shared/llm.py`, which reads `cv_settings.documentProvider` (`provider`: `ollama` | `openai`, plus `model`). When set to OpenAI and `secrets/openai-api-key` (or `OPENAI_API_KEY`) is present, those two processes call the OpenAI API; on failure they fall back to Ollama, then the existing deterministic templates. Job extract, profile update, and GitHub classify always use Ollama. Toggle and pick the model in Settings → Document generation.

The model registry lives in `cv_shared/openai_client.py`. Each entry records its free-tier bucket (`standard` = 1M tokens/day, `mini` = 10M tokens/day, both resetting at UTC midnight) and whether the model accepts `temperature` — GPT-5 reasoning models reject it, so the parameter is omitted for those.

### OpenAI token usage

Every successful OpenAI call appends to `cv_openaiUsage` (see [COLLECTIONS.md](COLLECTIONS.md)). `GET /openai/usage` returns today's spend against the selected model's daily allowance and powers the Settings progress bar. With an optional admin key in `secrets/openai-admin-key`, it also queries `/v1/organization/usage/completions` (60s cache) for the org-wide total, which is the number the shared free allowance actually applies to; without it the bar shows this app's spend only.

## Remote access

No public inbound. Use WireGuard + SSH port forward:

```bash
ssh -L 7545:localhost:7545 -L 8000:localhost:8000 user@legion-wireguard-ip
```

Then open `http://localhost:7545`.

## Evidence grounding

Every resume claim must cite an `evidence` document linked to `workHistory` and/or `projects`. The matcher and document generator must not invent experience.

Resume packages go through an explicit **tailor** step: achievements are addressed as `work:{id}:b{i}` / `project:{id}:b{i}`, the LLM (Ollama or OpenAI per Settings) may only select and lightly rewrite with a `sourceId`, and the app verifies every claim against the approved catalog before RenderCV or legacy PDF rendering. See [RESUME_PIPELINE.md](RESUME_PIPELINE.md).

## Stage 2A intake

Hourly worker (and `POST /ingest/run`) pulls Gmail job alerts → normalize/dedupe → Bay Area location gate → SWE title gate → `analyze_job` for listings that pass **both**. Config: [`config/location.json`](../config/location.json) and [`config/roleFilter.json`](../config/roleFilter.json). Setup: [GMAIL_SETUP.md](GMAIL_SETUP.md). Settings toggles in `cv_settings.gmailIngest` gate which alert senders are processed. After editing either config, restart API/worker or call `reload_location_config()` / `reload_role_filter_config()`.

## Stage 2B Greenhouse watchlist

Same ingest run also polls enabled Greenhouse boards from `cv_jobSources` when `cv_settings.atsIngest.greenhouse` is true. Public boards API (`boards-api.greenhouse.io`) — no API key. Same location + role gates as Gmail. Setup: [GREENHOUSE_SETUP.md](GREENHOUSE_SETUP.md). Sources UI lists last poll / errors; Settings holds the master ATS toggle.

## Stage 2C Ashby watchlist

Same ingest also polls enabled Ashby boards (`ats: "ashby"`) when `cv_settings.atsIngest.ashby` is true. Public posting API (`api.ashbyhq.com/posting-api/job-board/{slug}`) — no API key; descriptions included in the list response. Setup: [ASHBY_SETUP.md](ASHBY_SETUP.md).

## Stage 4 GitHub evidence

Worker cron at `:30` UTC (and manual Sync on Repositories) polls enabled repos in `cv_repositories` when `cv_settings.githubEvidence.enabled` is true. PAT in `secrets/github-token`. Commits by configured author logins are classified (Ollama + heuristics) into `cv_evidence` / skill ladder upgrades; `profileVersion` bumps trigger rescore of stale matches. Setup: [GITHUB_SETUP.md](GITHUB_SETUP.md).

## Manual URL intake queue

Analyze queues one or more job URLs into `cv_intakeQueue`. `POST /ingest/queue` enqueues and kicks `sources=manual` ingest on the **analyze** lane when that lane is idle. Inbox Fetch / hourly `sources=all` runs on a separate **inbox** lane and does **not** drain the Analyze queue. Drain path: claim pending → Greenhouse/Ashby single-job API when the URL matches → else enrich/paste → normalize → upsert → auto-analyze (no auto-drop). Blocked pages become `needsPaste` until a description is attached. Sync `POST /jobs` create+analyze remains for API compat; Analyze uses the queue.

## Stage 6 apply agent

Long-running Node service (`cv/services/agent`) drives a **persistent Chromium profile** with Playwright. MVP entry is a configured **Glassdoor Easy Apply search** (Indeed Smart Apply wizard). CV Inbox becomes an upstream first step later.

```text
Copilot mode (Easy Apply Local|Remote) → Glassdoor URL → extract → ingest/score
  → package (resume + cover letter via documentProvider) → Easy Apply
  → Indeed Smart Apply (tech Yes, resume, latest role; cover letter when requested) → human Approve submit
  → applicationStatus=pending → skip on later runs
```

- Control plane: HTTP + SSE/WebSocket on `:8010` (proxied as `/agent-api`)
- **Default topology**: host `npm start` owns `:8010`. Compose `agent` is opt-in via profile `headless-agent`
- Copilot **Apply mode** ToggleGroup: Easy Apply Local/Remote enabled; Company Apply stubs disabled
- Live browser preview + optional headed Chromium window; human takeover auto-pauses on click/type
- Tech Yes/No → `AUTO_YES`; legal/uncertain → Input queue; submit always requires approval (for now)
- Latest work role from `cv_workHistory` via `GET /agent/profile` (`latestRole`)
- Applied-job skip: any `apply`/`pending`/`round*`/`rejected` status
- Setup: [AGENT_SETUP.md](AGENT_SETUP.md)

## Role families

Matching detects role family (`systems`, `product`, `mobile`, `ai`) and leads generated documents with the matching evidence source (Capital One systems vs SwayQuest product vs mobile).
