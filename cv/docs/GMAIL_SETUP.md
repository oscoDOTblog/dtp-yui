# Gmail inbox setup (job-alert intake)

Stage 2A pulls job listings from **Gmail job-alert emails**, normalizes them into `cv_jobs`, applies the Bay Area location gate, and auto-analyzes eligible jobs into the Inbox.

This guide is the operator checklist. Secrets stay on the Legion under `cv/secrets/` (gitignored).

## 1. Dedicated vs personal inbox

**Recommended:** a dedicated Gmail account used only for job alerts (e.g. `yourname.jobs@gmail.com`).

If you must use a personal inbox:

- Create a Gmail label **`JobAlerts`**
- Add filters so only alert senders get that label
- Keep personal mail unlabeled so ingest stays quiet

## 2. Google Cloud OAuth (Desktop client)

1. Open [Google Cloud Console](https://console.cloud.google.com/)
2. Create or select a project (e.g. `dtp-yui-cv`)
3. Enable **Gmail API** (APIs & Services → Library → Gmail API → Enable)
4. Configure **OAuth consent screen**
   - User type: External (or Internal if Workspace)
   - App name: `DTP-CV` (local)
   - Scopes later: Gmail readonly (+ modify if you want the Processed label)
5. Create credentials → **OAuth client ID** → Application type **Desktop app**
6. Download the JSON and save it as:

```text
cv/secrets/gmail-client-secret.json
```

Do not commit this file.

## 3. First-time auth (token file)

On the host (not inside Docker), from `cv/`:

```bash
# One-time: install Google auth libs in a venv if needed
python3 -m venv .venv-gmail
source .venv-gmail/bin/activate
pip install google-api-python-client google-auth-oauthlib google-auth-httplib2

PYTHONPATH=services/shared python scripts/gmail_auth.py
```

What happens:

1. Browser opens for Google sign-in
2. Approve Gmail access for the job-alert account
3. Token is written to `cv/secrets/gmail-token.json`

**Scopes used (Stage 2A):**

- `https://www.googleapis.com/auth/gmail.readonly` — required
- `https://www.googleapis.com/auth/gmail.modify` — optional; only needed to apply the `AI Job Agent/Processed` label

Env overrides:

| Variable | Default |
|---|---|
| `SECRETS_DIR` | `./secrets` (or `/app/secrets` in Docker) |
| `GMAIL_CLIENT_SECRET` | `$SECRETS_DIR/gmail-client-secret.json` |
| `GMAIL_TOKEN` | `$SECRETS_DIR/gmail-token.json` |

Restart the worker after auth so it can read the token:

```bash
docker compose up -d --build worker api
```

Token refresh needs a **writable** `secrets/` mount on the worker (Compose mounts it read-write for the worker).

## 4. Job alert subscriptions

Create **narrow** alerts and send them all to this Gmail. Prefer Bay Area + role family over one giant national search.

### Locations (examples)

San Francisco Bay Area, San Francisco, Oakland, Berkeley, South San Francisco, San Mateo, Redwood City, Palo Alto, Mountain View, Sunnyvale, Santa Clara, San Jose, Remote California, Remote United States.

### Role families (examples)

Principal / Staff / Senior Software Engineer, Platform Engineer, Cloud Infrastructure, Solutions Architect, Forward Deployed Engineer, AI Applications Engineer, Founding Engineer, Technical Lead.

### Sources to enable

| Source | Typical from: |
|---|---|
| LinkedIn | `jobalerts-noreply@linkedin.com` |
| Indeed | `jobalerts-noreply@indeed.com` / `alert@indeed.com` |
| Built In | varies — check the From header |
| Wellfound (AngelList) | varies |
| Google Jobs / Google Alerts | `googlealerts-noreply@google.com` |
| Dice / ZipRecruiter / Glassdoor | their alert senders |

Tip: after the first alert arrives, open it → create a Gmail filter on that sender → apply label `JobAlerts`.

## 5. Gmail labels and filters

1. Create label **`JobAlerts`**
2. Optional nested labels: `JobAlerts/LinkedIn`, `JobAlerts/Indeed`, …
3. Filters: matching senders → Apply label `JobAlerts` (and Skip Inbox if you want a quiet primary inbox)
4. Optional: create label **`AI Job Agent/Processed`** for messages the worker has handled (`GMAIL_PROCESSED_LABEL=true`)

## 6. Search query the worker uses

Default (env `GMAIL_QUERY`):

```text
label:JobAlerts newer_than:2d
```

Broader sender-based alternative:

```text
newer_than:2d (
  label:JobAlerts OR
  from:jobalerts-noreply@linkedin.com OR
  from:jobalerts-noreply@indeed.com OR
  from:alert@indeed.com OR
  from:googlealerts-noreply@google.com
)
```

Set in `cv/.env`:

```bash
GMAIL_QUERY=label:JobAlerts newer_than:2d
GMAIL_PROCESSED_LABEL=false
```

## 7. Processed mail

When `GMAIL_PROCESSED_LABEL=true` and the modify scope was granted:

- After a message is ingested, the worker applies `AI Job Agent/Processed`
- Message ids are always recorded in Mongo `cv_gmailMessages` (idempotent even if labeling fails)

## 8. Digest emails → per-listing jobs

Glassdoor / Indeed / LinkedIn digests list many roles in one message. Ingest:

- Parses HTML listing cards (company, title, location, link)
- **Glassdoor**: dedicated table-card walker (company + rating, title link, location, salary, `jobListing` URL)
- Skips footer noise (unsubscribe, privacy, create alert)
- Creates **one `cv_jobs` row per listing** (no product cap; pathological guard at 100/message)
- Resolves redirects and best-effort fetches the listing page (~8s); falls back to card text if blocked
- Processes listings **sequentially** (fetch → upsert → analyze when Bay Area eligible)
- Runs in the **background** from `POST /ingest/run` — Inbox stays browsable and polls `/ingest/status`
- Stores `canonicalApplyUrl` / `url` / `sourceUrl` so **Open** works on cards and job detail

```bash
# Start (returns immediately with runId)
curl -X POST http://localhost:8000/ingest/run

# Live progress
curl http://localhost:8000/ingest/status

# Already running → HTTP 409
# Stop: POST /ingest/cancel  (force clear stuck lock: ?force=true)
```

Per-run listing cap: `INGEST_MAX_LISTINGS` (default **500**) truncates Gmail + Greenhouse in one Inbox run so a huge board poll cannot run for hours. Analyze queue runs on a separate lane with its own budget.

## 9. Settings — which alert senders to ingest

The **Settings** tab (`/settings`) is the source of truth for Gmail alert provider toggles. Stored in Mongo `cv_settings` (`_id: "app"`).

| Toggle | `detect_alert_source` values |
|---|---|
| LinkedIn | `linkedin-email` |
| Indeed | `indeed-email` |
| Glassdoor | `glassdoor-email` |
| Built In | `builtin-email` |
| Other alerts | Wellfound, Google, Dice, ZipRecruiter, unrecognized |

- `GMAIL_QUERY` / `JobAlerts` still control **which mail is fetched**
- Settings **Gmail ingest** master (`gmailIngest.enabled`) skips the Gmail API entirely when off
- Per-sender toggles control **which senders are processed** after fetch (disabled in UI when master is off)
- API: `GET /settings`, `PATCH /settings` with `{ "gmailIngest": { "enabled": false } }` or `{ "gmailIngest": { "glassdoorEmail": false } }`
- Worker and manual ingest both read the same doc — no redeploy when toggling
- **ATS boards** (Greenhouse, Ashby) have separate master toggles under Settings → ATS board ingest (`atsIngest.greenhouse`, `atsIngest.ashby`). See [GREENHOUSE_SETUP.md](GREENHOUSE_SETUP.md) and [ASHBY_SETUP.md](ASHBY_SETUP.md).

## 10. Telegram apply alerts

When a match scores **`recommendation=apply`** (≥ `SCORE_URGENT`, default 85), the API/worker can notify Telegram using the same env names as osco-dot-blog:

```bash
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

- Soft-fail if unset (ingest continues)
- Deduped via `telegramNotifiedAt` on the match (reprocess does not spam)
- Does **not** fire for `consider` / `skip` / `reject`

## 10b. Laptop vs remote (shared Mongo)

If the laptop UI and a remote processor share Atlas/Mongo, set on the **laptop**:

```bash
AUTO_PROCESSING_ENABLED=false
```

The worker then idles (no hourly ingest / GitHub cron / on-start ingest). Keep `AUTO_PROCESSING_ENABLED=true` (default) on the remote. Analyze and Generate documents still work on the laptop. See [README.md](../README.md#laptop-vs-remote-processor-shared-mongo).

## 11. Verification checklist

1. Client secret + token files exist under `cv/secrets/`
2. At least one recent message has label `JobAlerts`
3. Run a manual ingest:

```bash
curl -X POST http://localhost:8000/ingest/run
curl http://localhost:8000/ingest/status
```

4. Open http://localhost:3000 — job cards appear as each listing finishes; **Open** uses the stored listing URL
5. Re-run ingest — the same Gmail message must not create duplicates; second concurrent run returns 409
6. Check API logs / `cv_systemRuns` for type `ingest` with `listingsProcessed` progress
7. Open **Settings** — turn Glassdoor off, re-read alerts, confirm Glassdoor listings are skipped (`skippedDisabledSource`)

## 12. Security

- Never commit `gmail-client-secret.json` or `gmail-token.json`
- Bind services to `127.0.0.1` only; use WireGuard + SSH if remote
- Revoke access: Google Account → Security → Third-party access → remove the app, delete token file, re-run `scripts/gmail_auth.py`
- Prefer readonly scope if you do not need the Processed label

## Related

- [ROADMAP.md](ROADMAP.md) — Stage 2A+
- [COLLECTIONS.md](COLLECTIONS.md) — `cv_gmailMessages`, job intake fields
- [`../secrets/README.md`](../secrets/README.md) — secret file names
