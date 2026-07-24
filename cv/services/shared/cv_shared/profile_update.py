"""Apply free-text profile updates via Ollama into the candidate record."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ReturnDocument

from . import collections as C
from .db import get_db
from .ollama_client import chat, extract_json

logger = logging.getLogger(__name__)

UPDATE_SYSTEM = """You update a candidate profile from free-text notes.
Return exactly one JSON object. Include only keys that should change among:
name (string), location (string), email (string), phone (string),
linkedin (string URL), github (string URL),
preferredRoles (string array — full replacement when provided),
preferredLocations (string array — full replacement when provided),
minimumSalary (number),
remotePreference (one of: preferred, required, ok, open, unknown),
positioningSummaries (object; optional keys systems, product, mobile, ai —
  only include keys whose summary text should be replaced),
education (array of objects with institution, school, degree, location,
  graduatedAt — full replacement only when education clearly changes),
skillsToAdd (string array of new skill names to add),
summaryOfChanges (short string describing what changed).
Omit keys that should stay unchanged.
Do not invent facts that are neither in the update text nor already on the profile.
Prefer merging new information with existing strengths in positioningSummaries
rather than wiping unrelated detail.
"""

CANDIDATE_SCALAR_FIELDS = (
    "name",
    "location",
    "email",
    "phone",
    "linkedin",
    "github",
    "minimumSalary",
    "remotePreference",
)
CANDIDATE_LIST_FIELDS = ("preferredRoles", "preferredLocations", "education")
POSITIONING_KEYS = ("systems", "product", "mobile", "ai")
REMOTE_OK = {"preferred", "required", "ok", "open", "unknown"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _skill_id_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40]
    return f"skill_{slug or uuid.uuid4().hex[:8]}"


def _sanitize_patch(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Model did not return a JSON object")

    patch: dict[str, Any] = {}

    for key in CANDIDATE_SCALAR_FIELDS:
        if key not in raw or raw[key] is None:
            continue
        if key == "minimumSalary":
            try:
                patch[key] = int(raw[key])
            except (TypeError, ValueError):
                continue
            continue
        if key == "remotePreference":
            value = str(raw[key]).strip().lower()
            if value in REMOTE_OK:
                patch[key] = value
            continue
        value = str(raw[key]).strip()
        if value:
            patch[key] = value

    for key in CANDIDATE_LIST_FIELDS:
        if key not in raw or raw[key] is None:
            continue
        items = raw[key]
        if not isinstance(items, list):
            continue
        if key == "education":
            cleaned = []
            for edu in items:
                if not isinstance(edu, dict):
                    continue
                entry = {
                    k: str(edu[k]).strip()
                    for k in (
                        "institution",
                        "school",
                        "degree",
                        "location",
                        "graduatedAt",
                    )
                    if edu.get(k)
                }
                if entry.get("institution") or entry.get("degree"):
                    cleaned.append(entry)
            if cleaned:
                patch[key] = cleaned
            continue
        cleaned = [str(item).strip() for item in items if str(item).strip()]
        if cleaned:
            patch[key] = cleaned

    summaries = raw.get("positioningSummaries")
    if isinstance(summaries, dict):
        cleaned_summaries = {}
        for key in POSITIONING_KEYS:
            if key not in summaries or summaries[key] is None:
                continue
            text = str(summaries[key]).strip()
            if text:
                cleaned_summaries[key] = text
        if cleaned_summaries:
            patch["positioningSummaries"] = cleaned_summaries

    skills = raw.get("skillsToAdd")
    if isinstance(skills, list):
        cleaned_skills = [str(s).strip() for s in skills if str(s).strip()]
        if cleaned_skills:
            patch["skillsToAdd"] = cleaned_skills

    summary = raw.get("summaryOfChanges")
    if summary:
        patch["summaryOfChanges"] = str(summary).strip()

    return patch


def _upsert_skills(skill_names: list[str]) -> list[str]:
    db = get_db()
    now = _now()
    added: list[str] = []
    for name in skill_names:
        existing = db[C.SKILLS].find_one(
            {
                "candidateId": "primary-candidate",
                "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"},
            }
        )
        if existing:
            continue
        skill_id = _skill_id_slug(name)
        n = 0
        while db[C.SKILLS].find_one({"_id": skill_id}):
            n += 1
            skill_id = f"{_skill_id_slug(name)}_{n}"
        db[C.SKILLS].insert_one(
            {
                "_id": skill_id,
                "candidateId": "primary-candidate",
                "name": name,
                "category": "other",
                "confidence": 0.5,
                "evidenceLevel": "mentioned",
                "approvedForResume": False,
                "projectIds": [],
                "workHistoryIds": [],
                "evidenceIds": [],
                "aliases": [],
                "updatedAt": now,
            }
        )
        added.append(name)
    return added


def update_profile_from_text(text: str) -> dict[str, Any]:
    """Parse free-text update with Ollama and merge into primary candidate."""
    note = (text or "").strip()
    if not note:
        raise ValueError("Update text is required")
    if len(note) > 20000:
        raise ValueError("Update text is too long (max 20000 characters)")

    db = get_db()
    candidate = db[C.CANDIDATES].find_one({"_id": "primary-candidate"})
    if not candidate:
        raise KeyError("Candidate not seeded. POST /seed first.")

    current = {
        k: candidate.get(k)
        for k in (
            "name",
            "location",
            "email",
            "phone",
            "linkedin",
            "github",
            "education",
            "preferredRoles",
            "preferredLocations",
            "minimumSalary",
            "remotePreference",
            "positioningSummaries",
            "profileVersion",
        )
    }

    prompt = (
        "Current candidate profile JSON:\n"
        f"{current}\n\n"
        "New information to apply:\n"
        f"{note}\n\n"
        "Return JSON patch only."
    )
    raw = chat(prompt, system=UPDATE_SYSTEM, temperature=0.1)
    patch = _sanitize_patch(extract_json(raw))

    skills_to_add = patch.pop("skillsToAdd", [])
    summary_of_changes = patch.pop("summaryOfChanges", "") or "Profile updated."

    set_fields: dict[str, Any] = {"updatedAt": _now()}
    changed_fields: list[str] = []

    for key in CANDIDATE_SCALAR_FIELDS + CANDIDATE_LIST_FIELDS:
        if key in patch:
            set_fields[key] = patch[key]
            changed_fields.append(key)

    if "positioningSummaries" in patch:
        merged = dict(candidate.get("positioningSummaries") or {})
        merged.update(patch["positioningSummaries"])
        set_fields["positioningSummaries"] = merged
        changed_fields.append("positioningSummaries")

    skills_added = _upsert_skills(skills_to_add) if skills_to_add else []
    if skills_added:
        changed_fields.append("skills")

    if not changed_fields:
        return {
            "candidate": candidate,
            "changedFields": [],
            "skillsAdded": [],
            "summaryOfChanges": "No structured changes detected from that text.",
            "profileVersion": int(candidate.get("profileVersion") or 1),
        }

    current_version = int(candidate.get("profileVersion") or 1)
    new_version = current_version + 1
    set_fields["profileVersion"] = new_version

    history = list(candidate.get("updateHistory") or [])
    history.append(
        {
            "at": set_fields["updatedAt"],
            "summary": summary_of_changes,
            "changedFields": changed_fields,
            "sourceText": note[:2000],
        }
    )
    set_fields["updateHistory"] = history[-20:]

    updated = db[C.CANDIDATES].find_one_and_update(
        {"_id": "primary-candidate"},
        {"$set": set_fields},
        return_document=ReturnDocument.AFTER,
    )

    return {
        "candidate": updated,
        "changedFields": changed_fields,
        "skillsAdded": skills_added,
        "summaryOfChanges": summary_of_changes,
        "profileVersion": new_version,
    }
