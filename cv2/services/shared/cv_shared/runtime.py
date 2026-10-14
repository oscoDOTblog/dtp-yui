"""Host runtime flags (laptop debug vs remote processor)."""

from __future__ import annotations

import os


def auto_processing_enabled() -> bool:
    """True when this host may run automatic background processing.

    Set ``AUTO_PROCESSING_ENABLED=false`` on a laptop that shares Mongo with a
    remote processor so hourly ingest / GitHub cron do not collide.
    User-triggered one-offs (analyze, generate docs, manual Run ingest) stay
    allowed on the API regardless of this flag.
    """
    return os.environ.get("AUTO_PROCESSING_ENABLED", "true").lower() in (
        "1",
        "true",
        "yes",
    )


# Back-compat alias
processing_enabled = auto_processing_enabled
