"""Gmail API client helpers."""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

SCOPES_READONLY = ["https://www.googleapis.com/auth/gmail.readonly"]
SCOPES_MODIFY = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]

DEFAULT_QUERY = "label:JobAlerts newer_than:2d"


def secrets_dir() -> Path:
    return Path(os.environ.get("SECRETS_DIR", "/app/secrets"))


def client_secret_path() -> Path:
    return Path(
        os.environ.get("GMAIL_CLIENT_SECRET")
        or (secrets_dir() / "gmail-client-secret.json")
    )


def token_path() -> Path:
    return Path(os.environ.get("GMAIL_TOKEN") or (secrets_dir() / "gmail-token.json"))


def gmail_query() -> str:
    return (os.environ.get("GMAIL_QUERY") or DEFAULT_QUERY).strip()


def processed_label_enabled() -> bool:
    return os.environ.get("GMAIL_PROCESSED_LABEL", "false").lower() in (
        "1",
        "true",
        "yes",
    )


def credentials_available() -> bool:
    return client_secret_path().is_file() and token_path().is_file()


def build_gmail_service():
    """Build an authenticated Gmail API service. Raises if creds missing."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "Google API packages not installed. "
            "Add google-api-python-client google-auth-oauthlib google-auth-httplib2"
        ) from exc

    secret = client_secret_path()
    token = token_path()
    if not secret.is_file():
        raise FileNotFoundError(f"Missing Gmail client secret: {secret}")
    if not token.is_file():
        raise FileNotFoundError(
            f"Missing Gmail token: {token}. Run scripts/gmail_auth.py first."
        )

    scopes = SCOPES_MODIFY if processed_label_enabled() else SCOPES_READONLY
    creds = Credentials.from_authorized_user_file(str(token), scopes)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError(
                "Gmail token invalid/expired. Re-run scripts/gmail_auth.py"
            )

    return build("gmail", "v1", credentials=creds, cache_discovery=False)
