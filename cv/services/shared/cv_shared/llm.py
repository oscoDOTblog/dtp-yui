"""LLM dispatcher — routes document generation to OpenAI or Ollama."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from . import ollama_client
from . import openai_client

logger = logging.getLogger(__name__)

# Processes that honor cv_settings.documentProvider (OpenAI multi-stage + simple path)
DOCUMENT_PROVIDER_PROCESSES = (
    "coverLetter",
    "resumeTailor",
    "jobAnalyzer",
    "evidenceRanker",
    "resumeCritic",
    "consistencyReview",
)


@dataclass(frozen=True)
class LlmResult:
    text: str
    provider: str  # "openai" | "ollama"
    model: str | None = None


def _openai_target(process: str | None) -> str | None:
    """Model id to use when this process should go to OpenAI, else None."""
    if not process or process not in DOCUMENT_PROVIDER_PROCESSES:
        return None
    try:
        from .settings import get_document_provider_settings

        config = get_document_provider_settings()
    except Exception as exc:
        logger.warning(
            "Could not read documentProvider from settings; using ollama: %s", exc
        )
        return None
    if config.get("provider") != "openai":
        return None
    return config.get("model") or openai_client.default_model()


def generate(
    prompt: str,
    *,
    system: str | None = None,
    temperature: float = 0.2,
    process: str | None = None,
    response_format: dict[str, Any] | str | None = None,
) -> LlmResult:
    """Generate text via the configured provider for document processes.

    For coverLetter / resumeTailor / jobAnalyzer / evidenceRanker / resumeCritic /
    consistencyReview when provider=openai and a key is present, try OpenAI first;
    on failure fall through to Ollama. All other processes (and openai without a key)
    use Ollama directly.
    """
    model = _openai_target(process)
    if model and openai_client.key_configured():
        try:
            result = openai_client.chat(
                prompt,
                system=system,
                temperature=temperature,
                model=model,
                response_format=response_format,
            )
            _record_usage(result, process)
            return LlmResult(
                text=result.text, provider="openai", model=result.model
            )
        except Exception as exc:
            logger.warning(
                "OpenAI failed for %s; falling back to Ollama: %s", process, exc
            )

    text = ollama_client.chat(
        prompt,
        system=system,
        temperature=temperature,
        think_process=process,
        response_format=response_format,
    )
    return LlmResult(
        text=text, provider="ollama", model=ollama_client.ollama_model()
    )


def _record_usage(result: openai_client.ChatResult, process: str | None) -> None:
    try:
        from .openai_usage import record_usage

        record_usage(
            model=result.model,
            process=process,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
    except Exception as exc:
        logger.warning("Could not record OpenAI usage: %s", exc)
