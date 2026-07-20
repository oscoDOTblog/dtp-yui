"""App settings stored in Mongo (UI as source of truth)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import collections as C
from .db import get_db

APP_SETTINGS_ID = "app"

GMAIL_INGEST_KEYS = (
    "linkedinEmail",
    "indeedEmail",
    "glassdoorEmail",
    "builtinEmail",
    "otherEmail",
)

ATS_INGEST_KEYS = ("greenhouse",)

DEFAULT_GMAIL_INGEST = {key: True for key in GMAIL_INGEST_KEYS}
DEFAULT_ATS_INGEST = {key: True for key in ATS_INGEST_KEYS}

ALERT_SOURCE_TO_KEY = {
    "linkedin-email": "linkedinEmail",
    "indeed-email": "indeedEmail",
    "glassdoor-email": "glassdoorEmail",
    "builtin-email": "builtinEmail",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_app_settings() -> dict[str, Any]:
    return {
        "_id": APP_SETTINGS_ID,
        "gmailIngest": dict(DEFAULT_GMAIL_INGEST),
        "atsIngest": dict(DEFAULT_ATS_INGEST),
        "updatedAt": _now(),
    }


def _normalize_gmail_ingest(raw: dict[str, Any] | None) -> dict[str, bool]:
    out = dict(DEFAULT_GMAIL_INGEST)
    if not isinstance(raw, dict):
        return out
    for key in GMAIL_INGEST_KEYS:
        if key in raw:
            out[key] = bool(raw[key])
    return out


def _normalize_ats_ingest(raw: dict[str, Any] | None) -> dict[str, bool]:
    out = dict(DEFAULT_ATS_INGEST)
    if not isinstance(raw, dict):
        return out
    for key in ATS_INGEST_KEYS:
        if key in raw:
            out[key] = bool(raw[key])
    return out


def get_app_settings() -> dict[str, Any]:
    """Return app settings, creating defaults if missing."""
    db = get_db()
    doc = db[C.SETTINGS].find_one({"_id": APP_SETTINGS_ID})
    if not doc:
        doc = default_app_settings()
        db[C.SETTINGS].insert_one(doc)
        return doc

    gmail = _normalize_gmail_ingest(doc.get("gmailIngest"))
    ats = _normalize_ats_ingest(doc.get("atsIngest"))
    needs_fix = gmail != doc.get("gmailIngest") or ats != doc.get("atsIngest")
    if needs_fix:
        db[C.SETTINGS].update_one(
            {"_id": APP_SETTINGS_ID},
            {"$set": {"gmailIngest": gmail, "atsIngest": ats, "updatedAt": _now()}},
        )
        doc = db[C.SETTINGS].find_one({"_id": APP_SETTINGS_ID}) or doc
    doc["gmailIngest"] = gmail
    doc["atsIngest"] = ats
    return doc


def patch_app_settings(partial: dict[str, Any]) -> dict[str, Any]:
    """Merge allowed gmailIngest / atsIngest bools. Ignores unknown keys."""
    db = get_db()
    current = get_app_settings()
    gmail = dict(current.get("gmailIngest") or DEFAULT_GMAIL_INGEST)
    ats = dict(current.get("atsIngest") or DEFAULT_ATS_INGEST)

    incoming_gmail = partial.get("gmailIngest") if isinstance(partial, dict) else None
    if isinstance(incoming_gmail, dict):
        for key in GMAIL_INGEST_KEYS:
            if key in incoming_gmail:
                gmail[key] = bool(incoming_gmail[key])

    incoming_ats = partial.get("atsIngest") if isinstance(partial, dict) else None
    if isinstance(incoming_ats, dict):
        for key in ATS_INGEST_KEYS:
            if key in incoming_ats:
                ats[key] = bool(incoming_ats[key])

    updated_at = _now()
    db[C.SETTINGS].update_one(
        {"_id": APP_SETTINGS_ID},
        {"$set": {"gmailIngest": gmail, "atsIngest": ats, "updatedAt": updated_at}},
        upsert=True,
    )
    return {
        "_id": APP_SETTINGS_ID,
        "gmailIngest": gmail,
        "atsIngest": ats,
        "updatedAt": updated_at,
    }


def gmail_ingest_key_for_alert_source(alert_source: str) -> str:
    return ALERT_SOURCE_TO_KEY.get((alert_source or "").strip(), "otherEmail")


def is_gmail_source_enabled(
    alert_source: str,
    settings: dict[str, Any] | None = None,
) -> bool:
    doc = settings if settings is not None else get_app_settings()
    gmail = _normalize_gmail_ingest(doc.get("gmailIngest"))
    key = gmail_ingest_key_for_alert_source(alert_source)
    return bool(gmail.get(key, True))


def is_ats_source_enabled(
    ats: str,
    settings: dict[str, Any] | None = None,
) -> bool:
    """Master Settings toggle for ATS board ingest (e.g. greenhouse)."""
    doc = settings if settings is not None else get_app_settings()
    ats_map = _normalize_ats_ingest(doc.get("atsIngest"))
    key = (ats or "").strip().lower()
    if key not in ATS_INGEST_KEYS:
        return False
    return bool(ats_map.get(key, True))
