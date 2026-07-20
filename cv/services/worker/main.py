"""CV worker: seed on startup + hourly Gmail ingest + GitHub stub."""

from __future__ import annotations

import logging
import os
import time

from apscheduler.schedulers.background import BackgroundScheduler

from cv_shared.db import ensure_indexes
from cv_shared.intake.pipeline import run_ingest
from cv_shared.seed import seed_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("cv.worker")


def ingest_jobs() -> None:
    """Stage 2A: Gmail job-alert ingestion."""
    try:
        summary = run_ingest(analyze=True)
        logger.info("ingest-jobs finished: %s", summary)
    except Exception:
        logger.exception("ingest-jobs failed")


def stub_scan_github() -> None:
    """Stage 4: GitHub repository polling (not implemented)."""
    logger.info("[stub] scan-github — Stage 4 not implemented yet")


def main() -> None:
    ensure_indexes()
    if os.environ.get("AUTO_SEED", "true").lower() in ("1", "true", "yes"):
        try:
            result = seed_all(force=False)
            logger.info("Seed result: %s", result)
        except Exception as exc:
            logger.exception("Seed failed: %s", exc)

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(ingest_jobs, "cron", minute=0, id="ingest-jobs")
    scheduler.add_job(stub_scan_github, "cron", minute=30, id="scan-github")
    scheduler.start()
    logger.info("Worker started (ingest hourly at :00)")

    # Optional: run once shortly after boot so first alerts appear without waiting
    if os.environ.get("INGEST_ON_START", "true").lower() in ("1", "true", "yes"):
        try:
            ingest_jobs()
        except Exception:
            logger.exception("startup ingest failed")

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        scheduler.shutdown()


if __name__ == "__main__":
    main()
