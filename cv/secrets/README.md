# Secrets (local only)

Place credential files here. Contents of this directory (except this README) are gitignored.

## Stage 2A — Gmail

- `gmail-client-secret.json` — Desktop OAuth client from Google Cloud Console
- `gmail-token.json` — created by `scripts/gmail_auth.py`

**Full setup:** [docs/GMAIL_SETUP.md](../docs/GMAIL_SETUP.md)

The worker mounts this directory **read-write** so OAuth tokens can refresh.

## Stage 4 — GitHub

- `github-token` — personal access token (Contents: Read on scanned repos)

**Full setup:** [docs/GITHUB_SETUP.md](../docs/GITHUB_SETUP.md)

## OpenAI (optional document generation)

- `openai-api-key` — OpenAI API key for cover letter + resume tailor when Settings → Document generation is set to OpenAI
- `openai-admin-key` — optional [admin key](https://platform.openai.com/settings/organization/admin-keys) used only to read org-wide daily token usage for the Settings progress bar

Alternatively set `OPENAI_API_KEY` / `OPENAI_ADMIN_API_KEY` in `.env`. The model is chosen in the Settings UI (`OPENAI_MODEL` is just the initial default). Restart the API (and worker if needed) after adding a key.

Without the admin key the usage bar still works, but counts only tokens this app spent — not other traffic sharing the same free daily allowance.
