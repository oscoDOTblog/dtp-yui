#!/usr/bin/env python3
"""Backfill descriptionMarkdown on cv_jobs.

For each job missing descriptionMarkdown:
  - If descriptionRaw looks like HTML: convert to markdown, rewrite descriptionRaw
    to plain text (and refresh contentHash).
  - Otherwise: copy descriptionRaw into descriptionMarkdown so the UI can render
    either field consistently.

Usage (from cv/):
  PYTHONPATH=services/shared python services/worker/scripts/backfill_description_markdown.py
  PYTHONPATH=services/shared python services/worker/scripts/backfill_description_markdown.py --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "shared"))

from cv_shared import collections as C  # noqa: E402
from cv_shared.db import get_db  # noqa: E402
from cv_shared.intake.greenhouse_source import html_to_text  # noqa: E402
from cv_shared.intake.html_markdown import (  # noqa: E402
    html_to_markdown,
    looks_like_html,
)


def _content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def backfill(*, dry_run: bool = False) -> int:
    db = get_db()
    query = {
        "$or": [
            {"descriptionMarkdown": {"$exists": False}},
            {"descriptionMarkdown": None},
            {"descriptionMarkdown": ""},
        ]
    }
    scanned = 0
    updated = 0
    html_converted = 0

    cursor = db[C.JOBS].find(query, no_cursor_timeout=True)
    try:
        for doc in cursor:
            scanned += 1
            raw = doc.get("descriptionRaw") or ""
            updates: dict = {}

            if looks_like_html(raw):
                md = html_to_markdown(raw)
                plain = html_to_text(raw)
                updates["descriptionMarkdown"] = md or None
                if plain and plain != raw:
                    updates["descriptionRaw"] = plain
                    updates["contentHash"] = _content_hash(plain)
                html_converted += 1
            else:
                # Plain text still renders fine via react-markdown
                updates["descriptionMarkdown"] = raw or None

            if not updates:
                continue

            updated += 1
            if dry_run:
                print(
                    f"[dry-run] {doc.get('_id')} html={looks_like_html(raw)} "
                    f"md_len={len(updates.get('descriptionMarkdown') or '')}"
                )
            else:
                db[C.JOBS].update_one({"_id": doc["_id"]}, {"$set": updates})
    finally:
        cursor.close()

    print(
        f"scanned={scanned} updated={updated} html_converted={html_converted} "
        f"dry_run={dry_run}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned updates without writing",
    )
    args = parser.parse_args()
    return backfill(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
