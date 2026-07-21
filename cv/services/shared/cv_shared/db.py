import os
from functools import lru_cache

from pymongo import MongoClient
from pymongo.database import Database

from . import collections as C


@lru_cache(maxsize=1)
def get_client() -> MongoClient:
    uri = os.environ.get(
        "MONGO_URI",
        "mongodb://cvadmin:change-me-local@localhost:27017/DTP?authSource=admin",
    )
    return MongoClient(uri)


def get_db() -> Database:
    # Atlas / shared DTP database; CV collections are all prefixed with cv_
    name = os.environ.get("MONGO_DB", "DTP")
    return get_client()[name]


def ensure_indexes(db: Database | None = None) -> None:
    if db is None:
        db = get_db()
    db[C.JOBS].create_index("contentHash", unique=False)
    db[C.JOBS].create_index("status")
    db[C.JOBS].create_index("discoveredAt")
    db[C.JOB_MATCHES].create_index([("jobId", 1), ("candidateId", 1)])
    db[C.APPLICATIONS].create_index("jobId")
    db[C.USER_DECISIONS].create_index("jobId")
    db[C.SYSTEM_RUNS].create_index("startedAt")
    db[C.SKILLS].create_index("name")
    db[C.EVIDENCE].create_index("skillIds")
    db[C.GAP_INSIGHTS].create_index("totalSeen")
    db[C.GAP_INSIGHTS].create_index("status")
    db[C.GAP_INSIGHTS].create_index("normalizedName")
    db[C.JOBS].create_index("externalId", unique=True, sparse=True)
    db[C.JOBS].create_index("fingerprints.exact")
    db[C.JOBS].create_index("fingerprints.fuzzy")
    db[C.JOBS].create_index("source")
    db[C.JOBS].create_index("locationAssessment.bayAreaEligible")
    db[C.JOBS].create_index("roleAssessment.roleEligible")
    db[C.GMAIL_MESSAGES].create_index("processedAt")
    db[C.JOB_SOURCES].create_index("enabled")
    db[C.JOB_SOURCES].create_index("ats")
    db[C.JOB_SOURCES].create_index(
        [("ats", 1), ("boardToken", 1)],
        unique=True,
        name="ats_boardToken_unique",
    )
    db[C.INTAKE_QUEUE].create_index("status")
    db[C.INTAKE_QUEUE].create_index("createdAt")
    db[C.INTAKE_QUEUE].create_index("url")
    db[C.REPOSITORIES].create_index("enabled")
    db[C.REPOSITORIES].create_index("fullName", unique=True)
    db[C.REPOSITORY_SCANS].create_index("repositoryId")
    db[C.REPOSITORY_SCANS].create_index("sha")
