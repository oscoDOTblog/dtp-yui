"""Ollama HTTP client for extraction and drafting."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any
from urllib import error, request

logger = logging.getLogger(__name__)


def ollama_base_url() -> str:
    return os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip(
        "/"
    )


def ollama_model() -> str:
    return os.environ.get("OLLAMA_MODEL", "qwen3:8b")


def chat(prompt: str, system: str | None = None, temperature: float = 0.2) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": ollama_model(),
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
    }
    url = f"{ollama_base_url()}/api/chat"
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with request.urlopen(req, timeout=180) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return (body.get("message") or {}).get("content") or ""
    except error.URLError as exc:
        logger.warning("Ollama unavailable: %s", exc)
        raise RuntimeError(f"Ollama unavailable at {url}: {exc}") from exc


def extract_json(text: str) -> Any:
    """Pull the first JSON object/array from model output."""
    text = text.strip()
    # Strip common markdown fences
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"Could not parse JSON from model output: {text[:400]}")
