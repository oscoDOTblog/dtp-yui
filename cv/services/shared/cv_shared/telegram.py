"""Telegram notifications (osco-dot-blog env pattern)."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from . import collections as C
from .db import get_db

logger = logging.getLogger(__name__)


def telegram_configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def send_telegram_message(text: str) -> bool:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        logger.info(
            "Telegram not configured (TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing)"
        )
        return False
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": False,
            },
            timeout=15.0,
        )
        data = response.json()
        if data.get("ok"):
            return True
        logger.error("Telegram sendMessage error: %s", data.get("description"))
        return False
    except Exception as exc:
        logger.error("Telegram request error: %s", exc)
        return False


def notify_apply_match(job: dict[str, Any], match: dict[str, Any]) -> bool:
    """Send one Telegram alert for high-fit jobs (score ≥ SCORE_URGENT / apply).

    Dedupes via telegramNotifiedAt. Default apply band is 70+.
    """
    if (match or {}).get("recommendation") != "apply":
        return False
    if match.get("telegramNotifiedAt"):
        return False

    job_id = job.get("_id") or match.get("jobId")
    title = job.get("title") or "Untitled"
    company = job.get("company") or "Unknown"
    score = match.get("score")
    location = job.get("location") or "n/a"
    work_mode = job.get("workMode") or "unknown"
    url = (
        job.get("canonicalApplyUrl")
        or job.get("url")
        or job.get("sourceUrl")
        or ""
    )
    why = match.get("whyViable") or ""
    strong = match.get("strongMatches") or []
    strong_line = ""
    if strong and isinstance(strong[0], dict):
        strong_line = strong[0].get("requirement") or strong[0].get("skill") or ""

    urgent = int(os.environ.get("SCORE_URGENT", "70"))
    lines = [
        f"🎯 DTP-CV — APPLY ({urgent}+ fit)",
        "",
        f"Score: {score}/100 (apply)",
        f"{title} — {company}",
        f"Location: {location} · {work_mode}",
    ]
    if url:
        lines.append(f"Listing: {url}")
    if job_id:
        lines.append(f"Detail: /jobs/{job_id}")
    if why:
        lines.extend(["", why[:300]])
    elif strong_line:
        lines.extend(["", f"Strong match: {strong_line}"])

    sent = send_telegram_message("\n".join(lines))
    if sent and match.get("_id"):
        db = get_db()
        db[C.JOB_MATCHES].update_one(
            {"_id": match["_id"]},
            {
                "$set": {
                    "telegramNotifiedAt": datetime.now(timezone.utc).isoformat(),
                }
            },
        )
    return sent
