"""Ollama classification of commits into skill evidence."""

from __future__ import annotations

import logging
import re
from typing import Any

from ..ollama_client import chat, extract_json

logger = logging.getLogger(__name__)

EVIDENCE_LADDER = (
    "mentioned",
    "installed",
    "implemented",
    "substantial",
    "tested",
    "deployed",
    "maintained",
)

LADDER_RANK = {level: i for i, level in enumerate(EVIDENCE_LADDER)}

NEW_SKILL_MAX_LEVEL = "implemented"

SYSTEM_PROMPT = """You classify GitHub commits into resume skill evidence.
Return ONLY valid JSON (no markdown) with this shape:
{
  "items": [
    {
      "skillName": "string",
      "evidenceLevel": "mentioned|installed|implemented|substantial|tested|deployed|maintained",
      "claim": "one sentence grounded in the commit"
    }
  ]
}
Rules:
- Prefer matching known skills when listed.
- evidenceLevel must be honest: bugfix/docs → implemented; feature work → implemented/substantial;
  adding tests → tested; CI/deploy config → deployed; ongoing maintenance commits → maintained.
- Do not invent skills unrelated to files or message.
- If nothing skill-relevant, return {"items": []}.
- Max 5 items per commit.
"""


def ladder_rank(level: str | None) -> int:
    return LADDER_RANK.get((level or "").strip().lower(), LADDER_RANK["implemented"])


def clamp_level(level: str | None, *, max_level: str | None = None) -> str:
    raw = (level or "implemented").strip().lower()
    if raw not in LADDER_RANK:
        raw = "implemented"
    if max_level and ladder_rank(raw) > ladder_rank(max_level):
        return max_level
    return raw


def max_level(a: str | None, b: str | None) -> str:
    return a if ladder_rank(a) >= ladder_rank(b) else b


def _normalize_skill_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())


def match_existing_skill(
    skill_name: str,
    skills: list[dict[str, Any]],
) -> dict[str, Any] | None:
    needle = _normalize_skill_name(skill_name).lower()
    if not needle:
        return None
    for skill in skills:
        if _normalize_skill_name(skill.get("name") or "").lower() == needle:
            return skill
        for alias in skill.get("aliases") or []:
            if _normalize_skill_name(str(alias)).lower() == needle:
                return skill
    # soft contains match for short aliases
    for skill in skills:
        name = _normalize_skill_name(skill.get("name") or "").lower()
        if needle in name or name in needle:
            if min(len(needle), len(name)) >= 3:
                return skill
    return None


def classify_commit(
    *,
    full_name: str,
    message: str,
    files: list[str],
    known_skills: list[dict[str, Any]],
    bootstrap_floor: str | None = None,
) -> list[dict[str, Any]]:
    """Ask Ollama for evidence items; fall back to heuristic on failure."""
    skill_lines = []
    for s in known_skills[:80]:
        aliases = ", ".join(s.get("aliases") or [])
        skill_lines.append(
            f"- {s.get('name')} (level={s.get('evidenceLevel')}"
            + (f"; aliases={aliases}" if aliases else "")
            + ")"
        )
    file_preview = "\n".join(f"- {p}" for p in files[:40]) or "- (no files listed)"
    prompt = (
        f"Repository: {full_name}\n\n"
        f"Commit message:\n{message[:1500]}\n\n"
        f"Changed files:\n{file_preview}\n\n"
        f"Known skills:\n"
        + ("\n".join(skill_lines) if skill_lines else "- (none)")
        + "\n"
    )
    try:
        raw = chat(
            prompt,
            system=SYSTEM_PROMPT,
            temperature=0.1,
            think_process="githubClassify",
        )
        parsed = extract_json(raw)
        items = parsed.get("items") if isinstance(parsed, dict) else parsed
        if not isinstance(items, list):
            items = []
    except Exception as exc:
        logger.warning("Ollama commit classify failed; using heuristic: %s", exc)
        items = _heuristic_items(message, files, known_skills)

    out: list[dict[str, Any]] = []
    for item in items[:5]:
        if not isinstance(item, dict):
            continue
        name = _normalize_skill_name(str(item.get("skillName") or ""))
        if not name:
            continue
        existing = match_existing_skill(name, known_skills)
        max_allowed = None if existing else NEW_SKILL_MAX_LEVEL
        level = clamp_level(item.get("evidenceLevel"), max_level=max_allowed)
        if bootstrap_floor and existing:
            # First-scan floor can lift existing skills when justified by repo signals
            level = max_level(level, clamp_level(bootstrap_floor))
        claim = str(item.get("claim") or "").strip()
        if not claim:
            claim = f"Observed in {full_name}: {message.splitlines()[0][:120]}"
        out.append(
            {
                "skillName": existing.get("name") if existing else name,
                "skillId": existing.get("_id") if existing else None,
                "evidenceLevel": level,
                "claim": claim[:400],
                "isNew": existing is None,
            }
        )
    return out


def _heuristic_items(
    message: str,
    files: list[str],
    known_skills: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Lightweight path/message heuristics when Ollama is down."""
    blob = f"{message}\n" + "\n".join(files)
    blob_l = blob.lower()
    hits: list[dict[str, Any]] = []

    path_hints = [
        ("next.js", ["next.config", "app/page", "pages/"]),
        ("React", [".tsx", ".jsx", "components/"]),
        ("TypeScript", [".ts", ".tsx"]),
        ("Python", [".py", "requirements.txt", "pyproject.toml"]),
        ("Swift", [".swift", "Package.swift"]),
        ("Kotlin", [".kt", "build.gradle"]),
        ("Docker", ["Dockerfile", "docker-compose"]),
        ("AWS Lambda", ["serverless.yml", "template.yaml", "lambda"]),
        ("AWS DynamoDB", ["dynamodb"]),
        ("Tailwind CSS", ["tailwind.config"]),
        ("FastAPI", ["fastapi"]),
    ]

    level = "implemented"
    if any(x in blob_l for x in ("test", "spec", "jest", "pytest", "vitest")):
        level = "tested"
    if any(x in blob_l for x in (".github/workflows", "deploy", "dockerfile")):
        level = max_level(level, "deployed") if "test" in blob_l else "implemented"

    for skill_name, markers in path_hints:
        if any(m.lower() in blob_l for m in markers):
            existing = match_existing_skill(skill_name, known_skills)
            name = existing.get("name") if existing else skill_name
            hits.append(
                {
                    "skillName": name,
                    "evidenceLevel": level if existing else clamp_level(level, max_level=NEW_SKILL_MAX_LEVEL),
                    "claim": f"Commit touches {skill_name}-related paths or mentions.",
                }
            )
        if len(hits) >= 5:
            break

    if not hits and known_skills:
        # At least record activity against first path extension skill if any
        for skill in known_skills:
            name = (skill.get("name") or "").lower()
            if name and name in blob_l:
                hits.append(
                    {
                        "skillName": skill["name"],
                        "evidenceLevel": "implemented",
                        "claim": f"Commit mentions {skill['name']}.",
                    }
                )
                break
    return hits
