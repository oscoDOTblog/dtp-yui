"""OpenAI Chat Completions client for document generation."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request

logger = logging.getLogger(__name__)

API_BASE = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"

# Free daily token allowances for traffic shared with OpenAI. The two tiers are
# separate buckets and both reset at UTC midnight.
TIER_DAILY_TOKEN_LIMITS = {
    "standard": 1_000_000,
    "mini": 10_000_000,
}

# Curated Chat Completions models. GPT-5 reasoning models reject an explicit
# `temperature`, so each entry records whether the parameter may be sent.
OPENAI_MODELS: tuple[dict[str, Any], ...] = (
    {
        "id": "gpt-5.4",
        "label": "GPT-5.4",
        "tier": "standard",
        "supportsTemperature": False,
        "description": "Highest quality, slowest.",
    },
    {
        "id": "gpt-5.2",
        "label": "GPT-5.2",
        "tier": "standard",
        "supportsTemperature": False,
        "description": "Strong reasoning.",
    },
    {
        "id": "gpt-5.1",
        "label": "GPT-5.1",
        "tier": "standard",
        "supportsTemperature": False,
        "description": "Strong reasoning.",
    },
    {
        "id": "gpt-5",
        "label": "GPT-5",
        "tier": "standard",
        "supportsTemperature": False,
        "description": "Reasoning baseline.",
    },
    {
        "id": "gpt-5-chat-latest",
        "label": "GPT-5 Chat",
        "tier": "standard",
        "supportsTemperature": True,
        "description": "Non-reasoning chat model; honors temperature.",
    },
    {
        "id": "gpt-4.1",
        "label": "GPT-4.1",
        "tier": "standard",
        "supportsTemperature": True,
        "description": "Good long-form writing; honors temperature.",
    },
    {
        "id": "gpt-4o",
        "label": "GPT-4o",
        "tier": "standard",
        "supportsTemperature": True,
        "description": "Balanced general model.",
    },
    {
        "id": "gpt-5.4-mini",
        "label": "GPT-5.4 Mini",
        "tier": "mini",
        "supportsTemperature": False,
        "description": "Fast, 10M/day allowance.",
    },
    {
        "id": "gpt-5.4-nano",
        "label": "GPT-5.4 Nano",
        "tier": "mini",
        "supportsTemperature": False,
        "description": "Fastest, cheapest.",
    },
    {
        "id": "gpt-5-mini",
        "label": "GPT-5 Mini",
        "tier": "mini",
        "supportsTemperature": False,
        "description": "Fast reasoning.",
    },
    {
        "id": "gpt-5-nano",
        "label": "GPT-5 Nano",
        "tier": "mini",
        "supportsTemperature": False,
        "description": "Fastest reasoning.",
    },
    {
        "id": "gpt-4.1-mini",
        "label": "GPT-4.1 Mini",
        "tier": "mini",
        "supportsTemperature": True,
        "description": "Fast writing; honors temperature.",
    },
    {
        "id": "gpt-4.1-nano",
        "label": "GPT-4.1 Nano",
        "tier": "mini",
        "supportsTemperature": True,
        "description": "Fastest 4.1 tier.",
    },
    {
        "id": "gpt-4o-mini",
        "label": "GPT-4o Mini",
        "tier": "mini",
        "supportsTemperature": True,
        "description": "Default. Cheap, reliable, honors temperature.",
    },
)

MODELS_BY_ID = {m["id"]: m for m in OPENAI_MODELS}

# Reasoning families that reject an explicit temperature (gpt-5-chat excepted)
_NO_TEMPERATURE_RE = re.compile(r"^(o\d|gpt-5)")

_ORG_USAGE_CACHE_TTL_SECONDS = 60
_org_usage_cache: dict[str, Any] = {}


# --- credentials ---------------------------------------------------------


def secrets_dir() -> Path:
    return Path(os.environ.get("SECRETS_DIR", "/app/secrets"))


def openai_api_key_path() -> Path:
    return Path(
        os.environ.get("OPENAI_API_KEY_FILE") or (secrets_dir() / "openai-api-key")
    )


def openai_admin_key_path() -> Path:
    return Path(
        os.environ.get("OPENAI_ADMIN_KEY_FILE")
        or (secrets_dir() / "openai-admin-key")
    )


def _read_secret(path: Path, env_var: str) -> str | None:
    if path.is_file():
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    env_token = (os.environ.get(env_var) or "").strip()
    return env_token or None


def openai_api_key() -> str | None:
    """Load key from secrets file, then OPENAI_API_KEY env."""
    return _read_secret(openai_api_key_path(), "OPENAI_API_KEY")


def openai_admin_key() -> str | None:
    """Admin key for the org usage API (separate from the inference key)."""
    return _read_secret(openai_admin_key_path(), "OPENAI_ADMIN_KEY")


def key_configured() -> bool:
    return bool(openai_api_key())


def admin_key_configured() -> bool:
    return bool(openai_admin_key())


# --- model registry ------------------------------------------------------


def default_model() -> str:
    """Env-provided default, used when Settings has no model chosen."""
    candidate = (os.environ.get("OPENAI_MODEL") or "").strip()
    if candidate in MODELS_BY_ID:
        return candidate
    return DEFAULT_MODEL


def is_known_model(model_id: str) -> bool:
    return str(model_id or "").strip() in MODELS_BY_ID


def model_tier(model_id: str) -> str:
    """Which free-tier daily bucket a model draws from."""
    known = MODELS_BY_ID.get(str(model_id or "").strip())
    if known:
        return known["tier"]
    # Usage API returns dated snapshots (gpt-4o-mini-2024-07-18) — match by name
    name = str(model_id or "").lower()
    if "-mini" in name or "-nano" in name:
        return "mini"
    return "standard"


def daily_token_limit(model_id: str) -> int:
    return TIER_DAILY_TOKEN_LIMITS[model_tier(model_id)]


def supports_temperature(model_id: str) -> bool:
    known = MODELS_BY_ID.get(str(model_id or "").strip())
    if known:
        return bool(known["supportsTemperature"])
    name = str(model_id or "").strip().lower()
    if name.startswith("gpt-5-chat"):
        return True
    return not _NO_TEMPERATURE_RE.match(name)


def available_models() -> list[dict[str, Any]]:
    """Registry copy for the Settings UI, with each tier's daily allowance."""
    return [
        {**m, "dailyTokenLimit": TIER_DAILY_TOKEN_LIMITS[m["tier"]]}
        for m in OPENAI_MODELS
    ]


# --- chat ----------------------------------------------------------------


@dataclass(frozen=True)
class ChatResult:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def _to_response_format(
    response_format: dict[str, Any] | str | None,
) -> dict[str, Any] | None:
    """Convert bare JSON Schema (Ollama style) to OpenAI json_schema envelope."""
    if response_format is None:
        return None
    if response_format == "json":
        return {"type": "json_object"}
    if not isinstance(response_format, dict):
        return None
    if response_format.get("type") in ("json_schema", "json_object"):
        return response_format
    # Bare schema dict (same shape Ollama accepts as format=)
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "structured_output",
            "strict": False,
            "schema": response_format,
        },
    }


def _post_json(url: str, payload: dict[str, Any], api_key: str) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            pass
        logger.warning("OpenAI HTTP error %s: %s", exc.code, detail or exc)
        raise RuntimeError(
            f"OpenAI error at {url}: {exc.code} {detail or exc}"
        ) from exc
    except error.URLError as exc:
        logger.warning("OpenAI unavailable: %s", exc)
        raise RuntimeError(f"OpenAI unavailable at {url}: {exc}") from exc


def chat(
    prompt: str,
    system: str | None = None,
    temperature: float = 0.2,
    *,
    model: str | None = None,
    response_format: dict[str, Any] | str | None = None,
) -> ChatResult:
    """Chat with OpenAI Chat Completions. Returns text plus token usage."""
    api_key = openai_api_key()
    if not api_key:
        raise RuntimeError(
            "OpenAI API key not configured "
            "(secrets/openai-api-key or OPENAI_API_KEY)"
        )

    model_id = (model or "").strip() or default_model()

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload: dict[str, Any] = {"model": model_id, "messages": messages}
    # Reasoning models 400 on any explicit temperature
    if supports_temperature(model_id):
        payload["temperature"] = temperature
    fmt = _to_response_format(response_format)
    if fmt is not None:
        payload["response_format"] = fmt

    body = _post_json(f"{API_BASE}/chat/completions", payload, api_key)

    choices = body.get("choices") or []
    if not choices:
        raise RuntimeError("OpenAI returned no choices")
    message = choices[0].get("message") or {}
    usage = body.get("usage") or {}
    return ChatResult(
        text=(message.get("content") or "").strip(),
        model=str(body.get("model") or model_id),
        input_tokens=int(usage.get("prompt_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
    )


# --- org-wide usage (admin key) ------------------------------------------


def utc_day_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def utc_day_key(moment: datetime | None = None) -> str:
    return (moment or datetime.now(timezone.utc)).strftime("%Y-%m-%d")


def next_utc_reset() -> str:
    return (utc_day_start() + timedelta(days=1)).isoformat()


def _empty_tier_totals() -> dict[str, int]:
    return {tier: 0 for tier in TIER_DAILY_TOKEN_LIMITS}


def fetch_org_usage_today(force: bool = False) -> dict[str, Any]:
    """Org-wide tokens used today per tier, via the admin Usage API.

    Returns ``{"available": bool, "totalTokens": int, "byTier": {...},
    "error": str | None}``. Cached briefly so Settings polling stays cheap.
    """
    admin_key = openai_admin_key()
    if not admin_key:
        return {
            "available": False,
            "totalTokens": 0,
            "byTier": _empty_tier_totals(),
            "error": None,
        }

    day = utc_day_key()
    cached = _org_usage_cache.get("value")
    if (
        not force
        and cached
        and _org_usage_cache.get("day") == day
        and time.monotonic() - _org_usage_cache.get("at", 0)
        < _ORG_USAGE_CACHE_TTL_SECONDS
    ):
        return cached

    query = parse.urlencode(
        {
            "start_time": int(utc_day_start().timestamp()),
            "bucket_width": "1d",
            "group_by": "model",
            "limit": 1,
        }
    )
    url = f"{API_BASE}/organization/usage/completions?{query}"
    req = request.Request(
        url,
        headers={"Authorization": f"Bearer {admin_key}"},
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # admin key issues must not break Settings
        logger.warning("OpenAI org usage fetch failed: %s", exc)
        return {
            "available": False,
            "totalTokens": 0,
            "byTier": _empty_tier_totals(),
            "error": str(exc)[:200],
        }

    by_tier = _empty_tier_totals()
    total = 0
    for bucket in body.get("data") or []:
        for row in bucket.get("results") or []:
            tokens = int(row.get("input_tokens") or 0) + int(
                row.get("output_tokens") or 0
            )
            total += tokens
            by_tier[model_tier(row.get("model") or "")] += tokens

    value = {
        "available": True,
        "totalTokens": total,
        "byTier": by_tier,
        "error": None,
    }
    _org_usage_cache.update({"value": value, "day": day, "at": time.monotonic()})
    return value
