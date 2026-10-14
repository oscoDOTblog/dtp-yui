"""CV worker: seed on startup + hourly Gmail ingest + GitHub evidence scan."""

from __future__ import annotations

import logging
import os
import time

from apscheduler.schedulers.background import BackgroundScheduler

from cv_shared.db import ensure_indexes
from cv_shared.runtime import auto_processing_enabled
from cv_shared.seed import seed_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("cv.worker")


def ingest_jobs() -> None:
    """Stage 2A: Gmail job-alert ingestion (skips if API ingest already running)."""
    try:
        from cv_shared.intake.pipeline import get_running_ingest, run_ingest

        if get_running_ingest():
            logger.info("ingest-jobs skipped — another ingest is already running")
            return
        summary = run_ingest(analyze=True)
        logger.info("ingest-jobs finished: %s", summary)
    except Exception:
        logger.exception("ingest-jobs failed")


def scan_github() -> None:
    """Stage 4: GitHub evidence scan (skips if API scan already running)."""
    try:
        from cv_shared.github.pipeline import get_running_github_scan, run_github_scan
        from cv_shared.settings import is_github_evidence_enabled

        if not is_github_evidence_enabled():
            logger.info("scan-github skipped — GitHub evidence disabled in Settings")
            return
        if get_running_github_scan():
            logger.info("scan-github skipped — another scan is already running")
            return
        summary = run_github_scan(cron_mode=True)
        logger.info("scan-github finished: %s", summary)
    except Exception:
        logger.exception("scan-github failed")


def _idle_forever() -> None:
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        return


def main() -> None:
    ensure_indexes()
    if os.environ.get("AUTO_SEED", "true").lower() in ("1", "true", "yes"):
        try:
            result = seed_all(force=False)
            logger.info("Seed result: %s", result)
        except Exception as exc:
            logger.exception("Seed failed: %s", exc)

    if not auto_processing_enabled():
        logger.info(
            "Background processing disabled (AUTO_PROCESSING_ENABLED=false); idling. "
            "Hourly ingest/GitHub cron will not run on this host."
        )
        _idle_forever()
        return

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(ingest_jobs, "cron", minute=0, id="ingest-jobs")
    scheduler.add_job(scan_github, "cron", minute=30, id="scan-github")
    scheduler.start()
    logger.info("Worker started (ingest :00, github :30)")

    # Optional: run once shortly after boot so first alerts appear without waiting
    if os.environ.get("INGEST_ON_START", "true").lower() in ("1", "true", "yes"):
        try:
            ingest_jobs()
        except Exception:
            logger.exception("startup ingest failed")

    if os.environ.get("GITHUB_SCAN_ON_START", "false").lower() in (
        "1",
        "true",
        "yes",
    ):
        try:
            scan_github()
        except Exception:
            logger.exception("startup github scan failed")

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        scheduler.shutdown()


if __name__ == "__main__":
    main()
