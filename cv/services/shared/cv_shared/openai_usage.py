"""Local ledger of OpenAI token spend, bucketed by UTC day."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from . import collections as C
from .db import get_db
from .openai_client import (
    TIER_DAILY_TOKEN_LIMITS,
    model_tier,
    utc_day_key,
)

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _model_key(model: str) -> str:
    """Mongo update paths treat dots as nesting, so flatten model ids."""
    return str(model or "unknown").replace(".", "_").replace("$", "_")


def _empty_totals() -> dict[str, int]:
    return {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0, "requests": 0}


def record_usage(
    *,
    model: str,
    process: str | None,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Add one call to today's ledger. Never raises — accounting is best effort."""
    total = int(input_tokens or 0) + int(output_tokens or 0)
    if total <= 0:
        return
    day = utc_day_key()
    tier = model_tier(model)
    scopes = [
        "",
        f"byTier.{tier}.",
        f"byModel.{_model_key(model)}.",
    ]
    if process:
        scopes.append(f"byProcess.{process}.")

    increments: dict[str, int] = {}
    for scope in scopes:
        increments[f"{scope}inputTokens"] = int(input_tokens or 0)
        increments[f"{scope}outputTokens"] = int(output_tokens or 0)
        increments[f"{scope}totalTokens"] = total
        increments[f"{scope}requests"] = 1

    try:
        get_db()[C.OPENAI_USAGE].update_one(
            {"_id": day},
            {"$inc": increments, "$set": {"date": day, "updatedAt": _now()}},
            upsert=True,
        )
    except Exception as exc:
        logger.warning("Could not record OpenAI usage: %s", exc)


def get_local_usage(day: str | None = None) -> dict[str, Any]:
    """Today's recorded spend, with zeroed defaults when nothing is logged."""
    key = day or utc_day_key()
    doc: dict[str, Any] | None = None
    try:
        doc = get_db()[C.OPENAI_USAGE].find_one({"_id": key})
    except Exception as exc:
        logger.warning("Could not read OpenAI usage: %s", exc)

    out = {"date": key, **_empty_totals(), "byTier": {}, "byProcess": {}}
    if not doc:
        out["byTier"] = {tier: _empty_totals() for tier in TIER_DAILY_TOKEN_LIMITS}
        return out

    for field in _empty_totals():
        out[field] = int(doc.get(field) or 0)
    raw_tiers = doc.get("byTier") or {}
    out["byTier"] = {
        tier: {**_empty_totals(), **(raw_tiers.get(tier) or {})}
        for tier in TIER_DAILY_TOKEN_LIMITS
    }
    out["byProcess"] = doc.get("byProcess") or {}
    return out
