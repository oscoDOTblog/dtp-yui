# Secrets (local only)

Place credential files here. Contents of this directory (except this README) are gitignored.

## Stage 2A — Gmail

- `gmail-client-secret.json` — Desktop OAuth client from Google Cloud Console
- `gmail-token.json` — created by `scripts/gmail_auth.py`

**Full setup:** [docs/GMAIL_SETUP.md](../docs/GMAIL_SETUP.md)

The worker mounts this directory **read-write** so OAuth tokens can refresh.

## Later

Stage 4 may use:

- `github-token` or a GitHub App private key
