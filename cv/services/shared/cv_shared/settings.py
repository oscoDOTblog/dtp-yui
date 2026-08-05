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

# Master switch for all Gmail API ingest (sender keys are nested filters)
GMAIL_INGEST_MASTER_KEY = "enabled"

ATS_INGEST_KEYS = ("greenhouse", "ashby", "remotive")

LOOKBACK_PRESETS = ("1d", "7d", "30d", "90d", "365d", "all")

DEFAULT_GMAIL_INGEST = {
    GMAIL_INGEST_MASTER_KEY: True,
    **{key: True for key in GMAIL_INGEST_KEYS},
}
# remotive is opt-in (supplementary; public API is ~24h delayed)
DEFAULT_ATS_INGEST = {
    "greenhouse": True,
    "ashby": True,
    "remotive": False,
}
DEFAULT_GITHUB_EVIDENCE = {
    "enabled": True,
    "authorLogins": ["oscoDOTblog"],
    "defaultLookback": "7d",
    "discoverRepos": True,
}

# Drop gated listings before they hit Inbox (normalize → skip upsert/analyze)
DEFAULT_INGEST_FILTERS = {
    "dropOutOfArea": True,
    "dropWrongRole": True,
    # Greenhouse: list without content → prefilter → detail fetch
    "greenhouseTwoPhase": True,
}

# Ollama chat call sites that can enable thinking independently
OLLAMA_THINK_PROCESSES = (
    "jobExtract",
    "profileUpdate",
    "githubClassify",
    "coverLetter",
    "resumeTailor",
    "jobAnalyzer",
    "evidenceRanker",
    "resumeCritic",
    "consistencyReview",
)

DEFAULT_OLLAMA = {
    # Legacy global flag — still accepted on patch; seeds processes when migrating
    "think": False,
    "thinkByProcess": {key: False for key in OLLAMA_THINK_PROCESSES},
}

RESUME_RENDER_ENGINES = ("legacy", "rendercv")
DEFAULT_RESUME = {
    "renderEngine": "legacy",
    "templateId": "classic",
    "pages": 2,
}

DOCUMENT_PROVIDERS = ("ollama", "openai")
DEFAULT_DOCUMENT_PROVIDER = {
    "provider": "ollama",
    # Empty means "use the OPENAI_MODEL env default" (resolved on read)
    "model": "",
}

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
        "githubEvidence": dict(DEFAULT_GITHUB_EVIDENCE),
        "ingestFilters": dict(DEFAULT_INGEST_FILTERS),
        "ollama": {
            "think": False,
            "thinkByProcess": {key: False for key in OLLAMA_THINK_PROCESSES},
        },
        "resume": dict(DEFAULT_RESUME),
        "documentProvider": dict(DEFAULT_DOCUMENT_PROVIDER),
        "updatedAt": _now(),
    }


def _normalize_gmail_ingest(raw: dict[str, Any] | None) -> dict[str, bool]:
    out = dict(DEFAULT_GMAIL_INGEST)
    if not isinstance(raw, dict):
        return out
    if GMAIL_INGEST_MASTER_KEY in raw:
        out[GMAIL_INGEST_MASTER_KEY] = bool(raw[GMAIL_INGEST_MASTER_KEY])
    for key in GMAIL_INGEST_KEYS:
        if key in raw:
            out[key] = bool(raw[key])
    return out


def is_gmail_ingest_enabled(settings: dict[str, Any] | None = None) -> bool:
    """Master Settings toggle — when false, skip Gmail API entirely."""
    doc = settings if settings is not None else get_app_settings()
    gmail = _normalize_gmail_ingest(doc.get("gmailIngest"))
    if not gmail.get(GMAIL_INGEST_MASTER_KEY, True):
        return False
    # No point calling Gmail if every sender filter is off
    return any(bool(gmail.get(key, True)) for key in GMAIL_INGEST_KEYS)


def _normalize_ats_ingest(raw: dict[str, Any] | None) -> dict[str, bool]:
    out = dict(DEFAULT_ATS_INGEST)
    if not isinstance(raw, dict):
        return out
    for key in ATS_INGEST_KEYS:
        if key in raw:
            out[key] = bool(raw[key])
    return out


def _normalize_ingest_filters(raw: dict[str, Any] | None) -> dict[str, bool]:
    out = dict(DEFAULT_INGEST_FILTERS)
    if not isinstance(raw, dict):
        return out
    for key in DEFAULT_INGEST_FILTERS:
        if key in raw:
            out[key] = bool(raw[key])
    return out


def _normalize_github_evidence(raw: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(DEFAULT_GITHUB_EVIDENCE)
    out["authorLogins"] = list(DEFAULT_GITHUB_EVIDENCE["authorLogins"])
    if not isinstance(raw, dict):
        return out
    if "enabled" in raw:
        out["enabled"] = bool(raw["enabled"])
    if "discoverRepos" in raw:
        out["discoverRepos"] = bool(raw["discoverRepos"])
    if "authorLogins" in raw and isinstance(raw["authorLogins"], list):
        logins = [
            str(x).strip()
            for x in raw["authorLogins"]
            if str(x).strip()
        ]
        if logins:
            out["authorLogins"] = logins
    lookback = (raw.get("defaultLookback") or "").strip().lower()
    if lookback in LOOKBACK_PRESETS:
        out["defaultLookback"] = lookback
    return out


def _normalize_ollama(raw: dict[str, Any] | None) -> dict[str, Any]:
    by_process = {key: False for key in OLLAMA_THINK_PROCESSES}
    if not isinstance(raw, dict):
        return {"think": False, "thinkByProcess": by_process}

    legacy_think = bool(raw["think"]) if "think" in raw else None
    incoming = raw.get("thinkByProcess")
    has_process_map = isinstance(incoming, dict)
    for key in OLLAMA_THINK_PROCESSES:
        if has_process_map and key in incoming:
            by_process[key] = bool(incoming[key])
        elif legacy_think is not None and not has_process_map:
            # Migrate old single toggle → every process
            by_process[key] = legacy_think
        elif has_process_map and legacy_think is not None and key not in incoming:
            by_process[key] = legacy_think
        else:
            by_process[key] = False

    return {
        # Convenience mirror: true if any process has thinking on
        "think": any(by_process.values()),
        "thinkByProcess": by_process,
    }


def _normalize_resume(raw: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(DEFAULT_RESUME)
    if not isinstance(raw, dict):
        return out
    engine = str(raw.get("renderEngine") or "").strip().lower()
    if engine in RESUME_RENDER_ENGINES:
        out["renderEngine"] = engine
    template = str(raw.get("templateId") or "").strip()
    if template:
        out["templateId"] = template
    pages = raw.get("pages")
    if pages in (1, 2) or pages in ("1", "2"):
        out["pages"] = int(pages)
    return out


def _normalize_document_provider(raw: dict[str, Any] | None) -> dict[str, Any]:
    from .openai_client import default_model, is_known_model

    out = dict(DEFAULT_DOCUMENT_PROVIDER)
    out["model"] = default_model()
    if not isinstance(raw, dict):
        return out
    provider = str(raw.get("provider") or "").strip().lower()
    if provider in DOCUMENT_PROVIDERS:
        out["provider"] = provider
    model = str(raw.get("model") or "").strip()
    if model and is_known_model(model):
        out["model"] = model
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
    github = _normalize_github_evidence(doc.get("githubEvidence"))
    ingest_filters = _normalize_ingest_filters(doc.get("ingestFilters"))
    ollama = _normalize_ollama(doc.get("ollama"))
    resume = _normalize_resume(doc.get("resume"))
    document_provider = _normalize_document_provider(doc.get("documentProvider"))
    needs_fix = (
        gmail != doc.get("gmailIngest")
        or ats != doc.get("atsIngest")
        or github != doc.get("githubEvidence")
        or ingest_filters != doc.get("ingestFilters")
        or ollama != doc.get("ollama")
        or resume != doc.get("resume")
        or document_provider != doc.get("documentProvider")
    )
    if needs_fix:
        db[C.SETTINGS].update_one(
            {"_id": APP_SETTINGS_ID},
            {
                "$set": {
                    "gmailIngest": gmail,
                    "atsIngest": ats,
                    "githubEvidence": github,
                    "ingestFilters": ingest_filters,
                    "ollama": ollama,
                    "resume": resume,
                    "documentProvider": document_provider,
                    "updatedAt": _now(),
                }
            },
        )
        doc = db[C.SETTINGS].find_one({"_id": APP_SETTINGS_ID}) or doc
    doc["gmailIngest"] = gmail
    doc["atsIngest"] = ats
    doc["githubEvidence"] = github
    doc["ingestFilters"] = ingest_filters
    doc["ollama"] = ollama
    doc["resume"] = resume
    doc["documentProvider"] = document_provider
    return doc


def patch_app_settings(partial: dict[str, Any]) -> dict[str, Any]:
    """Merge allowed settings fields. Ignores unknown keys."""
    db = get_db()
    current = get_app_settings()
    gmail = dict(current.get("gmailIngest") or DEFAULT_GMAIL_INGEST)
    ats = dict(current.get("atsIngest") or DEFAULT_ATS_INGEST)
    github = _normalize_github_evidence(current.get("githubEvidence"))
    ingest_filters = _normalize_ingest_filters(current.get("ingestFilters"))
    ollama = _normalize_ollama(current.get("ollama"))
    resume = _normalize_resume(current.get("resume"))
    document_provider = _normalize_document_provider(current.get("documentProvider"))

    incoming_gmail = partial.get("gmailIngest") if isinstance(partial, dict) else None
    if isinstance(incoming_gmail, dict):
        if GMAIL_INGEST_MASTER_KEY in incoming_gmail:
            gmail[GMAIL_INGEST_MASTER_KEY] = bool(
                incoming_gmail[GMAIL_INGEST_MASTER_KEY]
            )
        for key in GMAIL_INGEST_KEYS:
            if key in incoming_gmail:
                gmail[key] = bool(incoming_gmail[key])
        gmail = _normalize_gmail_ingest(gmail)

    incoming_ats = partial.get("atsIngest") if isinstance(partial, dict) else None
    if isinstance(incoming_ats, dict):
        for key in ATS_INGEST_KEYS:
            if key in incoming_ats:
                ats[key] = bool(incoming_ats[key])

    incoming_gh = partial.get("githubEvidence") if isinstance(partial, dict) else None
    if isinstance(incoming_gh, dict):
        merged = dict(github)
        if "enabled" in incoming_gh:
            merged["enabled"] = bool(incoming_gh["enabled"])
        if "discoverRepos" in incoming_gh:
            merged["discoverRepos"] = bool(incoming_gh["discoverRepos"])
        if "authorLogins" in incoming_gh and isinstance(
            incoming_gh["authorLogins"], list
        ):
            merged["authorLogins"] = incoming_gh["authorLogins"]
        if "defaultLookback" in incoming_gh:
            merged["defaultLookback"] = incoming_gh["defaultLookback"]
        github = _normalize_github_evidence(merged)

    incoming_filters = (
        partial.get("ingestFilters") if isinstance(partial, dict) else None
    )
    if isinstance(incoming_filters, dict):
        for key in DEFAULT_INGEST_FILTERS:
            if key in incoming_filters:
                ingest_filters[key] = bool(incoming_filters[key])

    incoming_ollama = partial.get("ollama") if isinstance(partial, dict) else None
    if isinstance(incoming_ollama, dict):
        merged_ollama = {
            "think": ollama.get("think"),
            "thinkByProcess": dict(
                ollama.get("thinkByProcess") or DEFAULT_OLLAMA["thinkByProcess"]
            ),
        }
        # Global think patch sets every process (UI "all on/off" helper)
        if "think" in incoming_ollama and "thinkByProcess" not in incoming_ollama:
            value = bool(incoming_ollama["think"])
            merged_ollama["think"] = value
            merged_ollama["thinkByProcess"] = {
                key: value for key in OLLAMA_THINK_PROCESSES
            }
        if isinstance(incoming_ollama.get("thinkByProcess"), dict):
            for key in OLLAMA_THINK_PROCESSES:
                if key in incoming_ollama["thinkByProcess"]:
                    merged_ollama["thinkByProcess"][key] = bool(
                        incoming_ollama["thinkByProcess"][key]
                    )
        ollama = _normalize_ollama(merged_ollama)

    incoming_resume = partial.get("resume") if isinstance(partial, dict) else None
    if isinstance(incoming_resume, dict):
        merged_resume = dict(resume)
        if "renderEngine" in incoming_resume:
            merged_resume["renderEngine"] = incoming_resume["renderEngine"]
        if "templateId" in incoming_resume:
            merged_resume["templateId"] = incoming_resume["templateId"]
        if "pages" in incoming_resume:
            merged_resume["pages"] = incoming_resume["pages"]
        resume = _normalize_resume(merged_resume)

    incoming_doc_provider = (
        partial.get("documentProvider") if isinstance(partial, dict) else None
    )
    if isinstance(incoming_doc_provider, dict):
        merged_doc = dict(document_provider)
        if "provider" in incoming_doc_provider:
            merged_doc["provider"] = incoming_doc_provider["provider"]
        if "model" in incoming_doc_provider:
            merged_doc["model"] = incoming_doc_provider["model"]
        document_provider = _normalize_document_provider(merged_doc)

    updated_at = _now()
    db[C.SETTINGS].update_one(
        {"_id": APP_SETTINGS_ID},
        {
            "$set": {
                "gmailIngest": gmail,
                "atsIngest": ats,
                "githubEvidence": github,
                "ingestFilters": ingest_filters,
                "ollama": ollama,
                "resume": resume,
                "documentProvider": document_provider,
                "updatedAt": updated_at,
            }
        },
        upsert=True,
    )
    return {
        "_id": APP_SETTINGS_ID,
        "gmailIngest": gmail,
        "atsIngest": ats,
        "githubEvidence": github,
        "ingestFilters": ingest_filters,
        "ollama": ollama,
        "resume": resume,
        "documentProvider": document_provider,
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
    if not gmail.get(GMAIL_INGEST_MASTER_KEY, True):
        return False
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


def ingest_drop_reason(
    normalized: dict[str, Any],
    settings: dict[str, Any] | None = None,
) -> str | None:
    """If normalized job should be skipped before upsert, return counter key.

    Returns ``outOfArea`` / ``wrongRole`` / None.
    """
    doc = settings if settings is not None else get_app_settings()
    filters = _normalize_ingest_filters(doc.get("ingestFilters"))
    status = (normalized.get("status") or "").strip()
    if status == "out_of_area" and filters.get("dropOutOfArea", True):
        return "outOfArea"
    if status == "wrong_role" and filters.get("dropWrongRole", True):
        return "wrongRole"
    return None


def is_github_evidence_enabled(settings: dict[str, Any] | None = None) -> bool:
    """Master Settings toggle for GitHub evidence scanning."""
    doc = settings if settings is not None else get_app_settings()
    github = _normalize_github_evidence(doc.get("githubEvidence"))
    return bool(github.get("enabled", True))


def is_ollama_think_enabled(
    process: str | None = None,
    settings: dict[str, Any] | None = None,
) -> bool:
    """Whether Ollama thinking is on for a process (default false).

    process: jobExtract | profileUpdate | githubClassify | coverLetter | resumeTailor |
             jobAnalyzer | evidenceRanker | resumeCritic | consistencyReview
    If process is omitted, returns True only when any process has thinking on.
    """
    doc = settings if settings is not None else get_app_settings()
    ollama = _normalize_ollama(doc.get("ollama"))
    by_process = ollama.get("thinkByProcess") or {}
    if process:
        key = str(process).strip()
        if key not in OLLAMA_THINK_PROCESSES:
            return False
        return bool(by_process.get(key, False))
    return any(bool(by_process.get(key)) for key in OLLAMA_THINK_PROCESSES)


def get_resume_settings(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Normalized resume render settings (engine, template, pages)."""
    doc = settings if settings is not None else get_app_settings()
    return _normalize_resume(doc.get("resume"))


def get_document_provider_settings(
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalized {provider, model} for document package generation stages."""
    doc = settings if settings is not None else get_app_settings()
    return _normalize_document_provider(doc.get("documentProvider"))


def get_document_provider(settings: dict[str, Any] | None = None) -> str:
    """Return 'ollama' or 'openai' for multi-stage / simple document generation."""
    return get_document_provider_settings(settings)["provider"]
