"""Idempotent seed loader for candidate knowledge base."""

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


def seed_all(force: bool = False) -> dict:
    db = get_db()
    ensure_indexes(db)
    seed_path = _seed_dir()
    started = datetime.now(timezone.utc)
    results: dict[str, int] = {}

    if not force and db[C.CANDIDATES].find_one({"_id": "primary-candidate"}):
        logger.info("Candidate already seeded; skipping (use force=True to reseed)")
        return {"skipped": True, "reason": "already_seeded"}

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
