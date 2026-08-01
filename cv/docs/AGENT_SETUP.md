# Apply agent setup (Stage 6)

Hybrid browser copilot: Glassdoor discovery → CV score/package → Easy Apply (Indeed Smart Apply) → **human approval before submit**.

## Architecture

| Piece | Role |
|---|---|
| `services/agent` (host) | Node + Playwright runner — **owns :8010**; headed Chromium + Copilot preview |
| FastAPI `/agent/*` | Job ingest, runs/events, answer bank, `/agent/profile` (incl. latest work role) |
| Web `/copilot` | Mode picker, live preview, activity feed, input queue, controls |
| Compose `agent` | Opt-in headless only (`--profile headless-agent`) |

## Host agent (recommended)

```bash
cd cv
docker compose up -d          # api, web, mongo, worker — agent is NOT started
cd services/agent
cp .env.example .env          # once — HEADLESS=0 + PREVIEW=1
npm install
npx playwright install chromium   # once
npm start
```

Open http://localhost:7545/copilot → pick **Easy Apply (Local)** or **Easy Apply (Remote)** → **Start Glassdoor run**.

- Agent launches **installed Google Chrome** by default (`CV_AGENT_BROWSER_CHANNEL=chrome`) — not Playwright’s “Chrome for Testing” (Cloudflare often blocks that)
- If you see **Humans only / Verify you are human**, complete the checkbox in the Chrome window, then **Resume** in Copilot
- Chromium opens on the host; Copilot **Browser** panel keeps updating
- Click/type in Chromium → auto-pause → **Return control** when done
- Tech Yes/No questions are answered **Yes** automatically
- Relevant experience is prefilled from the latest seeded work-history role
- Final submit still waits for **Approve submit** in Copilot
- Already-applied jobs (`pending` / interview / `rejected`) are skipped

Keep in `cv/.env`:

```bash
AGENT_BASE_INTERNAL=http://host.docker.internal:8010
```

## Copilot apply modes

| Mode | Status | URL slot in `config/agent.json` |
|---|---|---|
| Easy Apply (Local) | enabled | `searchUrls.easyApplyLocal` |
| Easy Apply (Remote) | enabled | `searchUrls.easyApplyRemote` |
| Company Apply (Local) | disabled (coming soon) | `searchUrls.companyApplyLocal` |
| Company Apply (Remote) | disabled (coming soon) | `searchUrls.companyApplyRemote` |

Paste your Glassdoor results URLs (Easy Apply + Last week + salary filters, etc.) into the two Easy Apply slots. Filters stay in the URL — the agent does not click filter chips.

```json
{
  "applyMode": "easyApplyLocal",
  "searchUrls": {
    "easyApplyLocal": "https://www.glassdoor.com/Job/…",
    "easyApplyRemote": "https://www.glassdoor.com/Job/…",
    "companyApplyLocal": "",
    "companyApplyRemote": ""
  },
  "minimumScore": 60,
  "requireApprovalBeforeSubmit": true
}
```

## Config knobs

| Field / env | Purpose |
|---|---|
| `minimumScore` | Apply only if match ≥ this (default **60**) |
| `maxApplicationsPerRun` | Caps applies per run (default 1) |
| `CV_AGENT_HEADLESS` | `0` headed window (default); `1` headless |
| `CV_AGENT_PREVIEW` | Live JPEG preview (default on) |
| `CV_API_BASE` | FastAPI URL from host |

## Docker (opt-in headless agent)

```bash
docker compose --profile headless-agent up -d --build agent
```

Playwright version in `package.json` must match the Docker base image tag.

## Safety

- Never treats page text as system instructions
- Will not bypass CAPTCHA — pauses for manual solve
- Interacting with the Chromium window auto-pauses the agent
- Legal / demographic fields still go to the Copilot input queue
- No LinkedIn automation
- Submit only after Copilot approval
- Applied jobs are marked `pending` and skipped on later runs

## Success check

Easy Apply mode → open filtered Glassdoor URL → score ≥ 60 → Easy Apply → Indeed wizard (Yes on tech Qs, Capital One latest role, resume) → Approve submit → confirmation → `applicationStatus=pending` → next card skips that listing.
