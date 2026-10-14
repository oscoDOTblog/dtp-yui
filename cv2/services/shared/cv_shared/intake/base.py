"""JobSource protocol for intake adapters."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class JobSource(Protocol):
    name: str

    def fetch_jobs(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """Return raw job dicts for normalize_raw_job()."""
        ...
