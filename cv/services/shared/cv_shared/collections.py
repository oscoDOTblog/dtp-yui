"""Mongo collection names for the CV app inside database DTP.

All collections are prefixed with ``cv_`` so they sit alongside other DTP data.
"""

from __future__ import annotations

from pymongo.collection import Collection
from pymongo.database import Database

PREFIX = "cv_"

CANDIDATES = f"{PREFIX}candidates"
WORK_HISTORY = f"{PREFIX}workHistory"
SKILLS = f"{PREFIX}skills"
PROJECTS = f"{PREFIX}projects"
EVIDENCE = f"{PREFIX}evidence"
JOBS = f"{PREFIX}jobs"
JOB_MATCHES = f"{PREFIX}jobMatches"
APPLICATION_PACKAGES = f"{PREFIX}applicationPackages"
APPLICATIONS = f"{PREFIX}applications"
DOCUMENTS = f"{PREFIX}documents"
USER_DECISIONS = f"{PREFIX}userDecisions"
SYSTEM_RUNS = f"{PREFIX}systemRuns"

GAP_INSIGHTS = f"{PREFIX}gapInsights"
JOB_SOURCES = f"{PREFIX}jobSources"
GMAIL_MESSAGES = f"{PREFIX}gmailMessages"
SETTINGS = f"{PREFIX}settings"
INTAKE_QUEUE = f"{PREFIX}intakeQueue"
REPOSITORIES = f"{PREFIX}repositories"
REPOSITORY_SCANS = f"{PREFIX}repositoryScans"
APPLICATION_RUNS = f"{PREFIX}applicationRuns"
APPLICATION_EVENTS = f"{PREFIX}applicationEvents"
APPLICATION_ANSWERS = f"{PREFIX}applicationAnswers"
OPENAI_USAGE = f"{PREFIX}openaiUsage"

# Logical seed key -> actual Mongo collection name
SEED_COLLECTIONS = {
    "candidates": CANDIDATES,
    "workHistory": WORK_HISTORY,
    "skills": SKILLS,
    "projects": PROJECTS,
    "evidence": EVIDENCE,
}


def coll(db: Database, name: str) -> Collection:
    """Return ``db[cv_<name>]`` (adds prefix if missing)."""
    if name.startswith(PREFIX):
        return db[name]
    return db[f"{PREFIX}{name}"]
