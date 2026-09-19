#!/usr/bin/env python3
"""One-time Gmail OAuth for CV job-alert intake.

Usage (from cv/):
  PYTHONPATH=services/shared python scripts/gmail_auth.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow running without install into site-packages layout
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "shared"))

from cv_shared.intake.gmail_client import (  # noqa: E402
    SCOPES_MODIFY,
    SCOPES_READONLY,
    client_secret_path,
    processed_label_enabled,
    secrets_dir,
    token_path,
)


def main() -> int:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print(
            "Install: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2",
            file=sys.stderr,
        )
        return 1

    secrets_dir().mkdir(parents=True, exist_ok=True)
    secret = client_secret_path()
    token = token_path()
    if not secret.is_file():
        print(f"Missing client secret: {secret}", file=sys.stderr)
        print("Download Desktop OAuth JSON from Google Cloud Console.", file=sys.stderr)
        return 1

    scopes = SCOPES_MODIFY if processed_label_enabled() else SCOPES_READONLY
    # Also allow modify if user passes --modify
    if "--modify" in sys.argv:
        scopes = SCOPES_MODIFY

    flow = InstalledAppFlow.from_client_secrets_file(str(secret), scopes)
    creds = flow.run_local_server(port=0)
    token.write_text(creds.to_json(), encoding="utf-8")
    print(f"Wrote token: {token}")
    print("Restart the worker: docker compose up -d worker")
    return 0


if __name__ == "__main__":
    # Prefer local secrets when running on host
    os.environ.setdefault("SECRETS_DIR", str(ROOT / "secrets"))
    raise SystemExit(main())
