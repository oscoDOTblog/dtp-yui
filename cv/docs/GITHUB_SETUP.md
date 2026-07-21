# GitHub evidence setup (Stage 4)

Operator guide for the GitHub evidence engine: poll configured repos, classify commits into the skill evidence ladder, bump `profileVersion`, and rescore open jobs.

## What this does

- **Hourly cron at `:30` UTC** (worker): for each enabled repo, skip if HEAD SHA matches `lastSeenCommitSha`; otherwise scan commits in the default lookback window.
- **Manual Sync** (Repositories page): always walks the selected lookback (`1d` / `7d` / `30d` / `90d` / `365d` / `all`), ignoring the HEAD-SHA skip. Already-recorded commit SHAs are skipped unless **Force** is checked.
- Ollama classifies each new commit into skill/evidence updates. New evidence is `approvedForResume: false`. Skill `evidenceLevel` only upgrades (never downgrades).
- On profile changes, `profileVersion` increments and jobs with stale matches are re-analyzed.

## PAT setup

1. Create a GitHub personal access token (classic or fine-grained) with **Contents: Read** on the repos you scan (and metadata read).
2. Write the token (no trailing newline issues — a single line is fine) to:

```text
cv/secrets/github-token
```

3. Optional overrides:
   - `GITHUB_TOKEN_FILE` — absolute path to the token file
   - `GITHUB_TOKEN` — token string (prefer the file under secrets/)

The API and worker mount `cv/secrets/`. Rebuild containers after adding the token if they were already running without the file.

## Settings master toggle

1. Open **Settings** → **GitHub evidence**
2. Toggle **Evidence engine** on/off

| Control | Effect |
|---|---|
| Settings off | Cron and Sync return/skip |
| Settings on + repo disabled | That repo skipped |
| Settings on + repo enabled | Repo scanned |

## Repositories UI

1. Open **Repositories**
2. Choose **Lookback** (how far back to search for commits)
3. Optionally check **Force** to re-process commits already in `cv_repositoryScans`
4. **Sync all** or per-row **Sync**

Add repos as `owner/repo` (probes the GitHub API). Seed file: [`seed/repositories.json`](../seed/repositories.json).

```bash
curl -X POST 'http://localhost:8000/seed'
```

Identity fields upsert without wiping `lastSeenCommitSha` / errors. Operator-disabled repos stay disabled.

## Author filter

Only commits by logins in `githubEvidence.authorLogins` (default `oscoDOTblog`) are analyzed. Edit via Settings API:

```bash
curl -X PATCH 'http://localhost:8000/settings' \
  -H 'Content-Type: application/json' \
  -d '{"githubEvidence":{"authorLogins":["oscoDOTblog"]}}'
```

## API

| Route | Purpose |
|---|---|
| `GET /repositories` | List |
| `POST /repositories` | Add (`fullName`) |
| `PATCH /repositories/{id}` | Enable / branch / projectIds |
| `POST /repositories/sync` | Manual sync (`lookback`, optional `force`, `repositoryIds`) |
| `POST /repositories/{id}/sync` | Sync one repo |
| `GET /repositories/sync/status?runId=` | Poll run progress |

## Shallow clones

First successful scan may shallow-clone into `repository-cache/{owner}__{repo}` for bootstrap signals (tests/, CI, manifests). Cron does not re-clone every time.

## Env

| Variable | Default | Purpose |
|---|---|---|
| `GITHUB_TOKEN_FILE` | `$SECRETS_DIR/github-token` | PAT file path |
| `GITHUB_TOKEN` | (empty) | Inline PAT fallback |
| `REPOSITORY_CACHE_DIR` | `/app/repository-cache` | Clone cache |
| `GITHUB_SCAN_ON_START` | `false` | Worker runs one scan after boot |

If `PROFILE_VERSION` is set in the environment, match documents stamp that value instead of Mongo `candidate.profileVersion` — leave it unset in normal operation so bumps from GitHub scans take effect.

## Troubleshooting

- **400 GitHub evidence is disabled** — turn on Settings toggle
- **GitHub token missing** — create `secrets/github-token`
- **Ollama unavailable** — scan falls back to path/message heuristics; start Ollama for better classification
- **Private repo 404** — PAT needs access to that repo
