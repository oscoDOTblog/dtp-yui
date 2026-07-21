"""Idempotent seed loader for candidate knowledge base and job sources."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import collections as C
from .db import ensure_indexes, get_db

logger = logging.getLogger(__name__)

SEED_FILES = {
    "candidates": "candidates.json",
    "workHistory": "workHistory.json",
    "skills": "skills.json",
    "projects": "projects.json",
    "evidence": "evidence.json",
}


def _seed_dir() -> Path:
    return Path(os.environ.get("SEED_DIR", "/app/seed"))


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed_job_sources() -> int:
    """Upsert watchlist from seed/jobSources.json without wiping poll state.

    Runs independently of candidate seed so AUTO_SEED / POST /seed always
    refreshes identity fields even when the candidate is already present.
    """
    db = get_db()
    path = _seed_dir() / "jobSources.json"
    if not path.exists():
        logger.warning("Missing seed file: %s", path)
        return 0

    data = _load_json(path)
    docs = data if isinstance(data, list) else [data]
    now = _now()
    count = 0

    for doc in docs:
        source_id = doc.get("_id")
        if not source_id:
            continue
        ats = (doc.get("ats") or "greenhouse").strip()
        token = (doc.get("boardToken") or "").strip()
        if not token:
            continue

        existing = db[C.JOB_SOURCES].find_one({"_id": source_id})
        identity = {
            "name": (doc.get("name") or token).strip(),
            "ats": ats,
            "boardToken": token,
            "priority": int(doc.get("priority") or 0),
            "locations": list(doc.get("locations") or []),
            "careersUrl": (
                doc.get("careersUrl")
                or f"https://boards.greenhouse.io/{token}"
            ).strip(),
            "updatedAt": now,
        }

        if existing:
            # Never re-enable an operator-disabled source; never touch poll fields.
            db[C.JOB_SOURCES].update_one(
                {"_id": source_id},
                {"$set": identity},
            )
        else:
            insert_doc = {
                "_id": source_id,
                **identity,
                "enabled": bool(doc.get("enabled", True)),
                "lastPolledAt": None,
                "lastSuccessAt": None,
                "lastError": None,
                "lastJobCount": 0,
                "createdAt": now,
            }
            db[C.JOB_SOURCES].insert_one(insert_doc)
        count += 1

    logger.info("Seeded %s: %s documents", C.JOB_SOURCES, count)
    return count


def seed_repositories() -> int:
    """Upsert GitHub repos from seed/repositories.json without wiping scan state."""
    db = get_db()
    path = _seed_dir() / "repositories.json"
    if not path.exists():
        logger.warning("Missing seed file: %s", path)
        return 0

    data = _load_json(path)
    docs = data if isinstance(data, list) else [data]
    now = _now()
    count = 0

    for doc in docs:
        repo_id = doc.get("_id")
        full_name = (doc.get("fullName") or "").strip()
        if not repo_id or not full_name:
            continue

        existing = db[C.REPOSITORIES].find_one({"_id": repo_id})
        identity = {
            "fullName": full_name,
            "defaultBranch": (doc.get("defaultBranch") or "main").strip() or "main",
            "projectIds": list(doc.get("projectIds") or []),
            "updatedAt": now,
        }

        if existing:
            # Never re-enable an operator-disabled repo; never touch scan fields.
            db[C.REPOSITORIES].update_one({"_id": repo_id}, {"$set": identity})
        else:
            insert_doc = {
                "_id": repo_id,
                **identity,
                "enabled": bool(doc.get("enabled", True)),
                "lastSeenCommitSha": None,
                "lastScannedAt": None,
                "lastSuccessAt": None,
                "lastError": None,
                "lastCommitCount": 0,
                "clonePath": None,
                "createdAt": now,
            }
            db[C.REPOSITORIES].insert_one(insert_doc)
        count += 1

    logger.info("Seeded %s: %s documents", C.REPOSITORIES, count)
    return count


def seed_all(force: bool = False) -> dict:
    db = get_db()
    ensure_indexes(db)
    seed_path = _seed_dir()
    started = datetime.now(timezone.utc)
    results: dict[str, int] = {}

    # Job sources + repos always upsert (even when candidate seed is skipped).
    results[C.JOB_SOURCES] = seed_job_sources()
    results[C.REPOSITORIES] = seed_repositories()

    if not force and db[C.CANDIDATES].find_one({"_id": "primary-candidate"}):
        logger.info("Candidate already seeded; skipping (use force=True to reseed)")
        return {
            "skipped": True,
            "reason": "already_seeded",
            "results": results,
        }

    for logical_name, filename in SEED_FILES.items():
        collection = C.SEED_COLLECTIONS[logical_name]
        path = seed_path / filename
        if not path.exists():
            logger.warning("Missing seed file: %s", path)
            results[collection] = 0
            continue
        data = _load_json(path)
        docs = data if isinstance(data, list) else [data]
        count = 0
        for doc in docs:
            db[collection].replace_one({"_id": doc["_id"]}, doc, upsert=True)
            count += 1
        results[collection] = count
        logger.info("Seeded %s: %s documents", collection, count)

    run = {
        "_id": f"seed_{started.strftime('%Y%m%dT%H%M%SZ')}",
        "type": "seed",
        "startedAt": started.isoformat(),
        "finishedAt": datetime.now(timezone.utc).isoformat(),
        "results": results,
        "force": force,
    }
    db[C.SYSTEM_RUNS].replace_one({"_id": run["_id"]}, run, upsert=True)
    return {"skipped": False, "results": results}
