"""CV worker: seed on startup + APScheduler stubs for Stage 2/3."""

from __future__ import annotations

import logging
import os
import time

from apscheduler.schedulers.background import BackgroundScheduler

from cv_shared.db import ensure_indexes
from cv_shared.seed import seed_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("cv.worker")


def stub_ingest_jobs() -> None:
    """Stage 2: Gmail LinkedIn alert ingestion (not implemented)."""
    logger.info("[stub] ingest-jobs — Stage 2 not implemented yet")


def stub_scan_github() -> None:
    """Stage 3: GitHub repository polling (not implemented)."""
    logger.info("[stub] scan-github — Stage 3 not implemented yet")


def main() -> None:
    ensure_indexes()
    if os.environ.get("AUTO_SEED", "true").lower() in ("1", "true", "yes"):
        try:
            result = seed_all(force=False)
            logger.info("Seed result: %s", result)
        except Exception as exc:
            logger.exception("Seed failed: %s", exc)

    scheduler = BackgroundScheduler(timezone="UTC")
    # Hourly at :00 — Stage 2 stub
    scheduler.add_job(stub_ingest_jobs, "cron", minute=0, id="ingest-jobs")
    # Hourly at :30 — Stage 3 stub
    scheduler.add_job(stub_scan_github, "cron", minute=30, id="scan-github")
    scheduler.start()
    logger.info("Worker started with Stage 2/3 scheduler stubs")

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        scheduler.shutdown()


if __name__ == "__main__":
    main()
