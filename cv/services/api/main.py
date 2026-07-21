from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib import error, request as urlrequest

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pathlib import Path

from cv_shared import collections as C
from cv_shared.db import ensure_indexes, get_db
from cv_shared.documents import generate_application_package
from cv_shared.matching import analyze_job, content_hash
from cv_shared.seed import seed_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="CV Job Copilot API", version="0.1.0")

cors_origins = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class JobCreate(BaseModel):
    url: Optional[str] = None
    descriptionRaw: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    workMode: Optional[str] = None


class UrlFetchBody(BaseModel):
    url: str


class BulkDeleteBody(BaseModel):
    jobIds: list[str] = Field(default_factory=list)


class SettingsPatchBody(BaseModel):
    gmailIngest: Optional[dict[str, bool]] = None
    atsIngest: Optional[dict[str, bool]] = None
    githubEvidence: Optional[dict[str, Any]] = None


class SourceCreateBody(BaseModel):
    name: str
    boardToken: str
    ats: str = "greenhouse"
    priority: Optional[int] = 50
    locations: Optional[list[str]] = None
    enabled: Optional[bool] = True


class SourcePatchBody(BaseModel):
    enabled: Optional[bool] = None
    priority: Optional[int] = None
    locations: Optional[list[str]] = None
    name: Optional[str] = None


class RepositoryCreateBody(BaseModel):
    fullName: str
    defaultBranch: Optional[str] = None
    projectIds: Optional[list[str]] = None
    enabled: Optional[bool] = True


class RepositoryPatchBody(BaseModel):
    enabled: Optional[bool] = None
    defaultBranch: Optional[str] = None
    projectIds: Optional[list[str]] = None
    suggested: Optional[bool] = None
    dismissed: Optional[bool] = None


class RepositorySyncBody(BaseModel):
    lookback: str = "7d"
    repositoryIds: Optional[list[str]] = None
    force: Optional[bool] = False


class DecisionBody(BaseModel):
    decision: str = Field(..., description="apply | save | reject | draft")
    note: Optional[str] = None


class IntakeQueueBody(BaseModel):
    urls: Optional[Any] = None  # str | list[str]
    descriptionRaw: Optional[str] = None


class IntakeQueuePatchBody(BaseModel):
    descriptionRaw: str


def _serialize(doc: Any) -> Any:
    if doc is None:
        return None
    if isinstance(doc, list):
        return [_serialize(x) for x in doc]
    if isinstance(doc, dict):
        out = {}
        for k, v in doc.items():
            out[k] = _serialize(v)
        return out
    if hasattr(doc, "isoformat"):
        return doc.isoformat()
    return doc


def _try_fetch_url(url: str) -> dict:
    """Best-effort public page fetch. Returns structured success/blocked result."""
    url = (url or "").strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        return {
            "ok": False,
            "blocked": True,
            "reason": "URL must start with http:// or https://",
            "text": "",
            "titleHint": "",
        }

    req = urlrequest.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        with urlrequest.urlopen(req, timeout=25) as resp:
            status = getattr(resp, "status", 200) or 200
            raw = resp.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        return {
            "ok": False,
            "blocked": True,
            "reason": f"HTTP {exc.code}: page blocked or unavailable. Paste the job description below.",
            "text": "",
            "titleHint": "",
        }
    except error.URLError as exc:
        return {
            "ok": False,
            "blocked": True,
            "reason": f"Could not fetch URL ({exc.reason}). Paste the job description below.",
            "text": "",
            "titleHint": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "blocked": True,
            "reason": f"Fetch failed ({exc}). Paste the job description below.",
            "text": "",
            "titleHint": "",
        }

    title_hint = ""
    og = re.search(
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
        raw,
        flags=re.I,
    )
    if og:
        title_hint = og.group(1).strip()
    else:
        title_tag = re.search(r"<title[^>]*>([\s\S]*?)</title>", raw, flags=re.I)
        if title_tag:
            title_hint = re.sub(r"\s+", " ", title_tag.group(1)).strip()

    text = re.sub(r"<script[\s\S]*?</script>", " ", raw, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<noscript[\s\S]*?</noscript>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()[:20000]

    blocked_markers = (
        "captcha",
        "enable javascript",
        "sign in to continue",
        "log in to continue",
        "access denied",
        "unusual traffic",
        "cf-browser-verification",
        "linkedin.com/login",
        "authwall",
    )
    lower = text.lower()
    soft_block = any(m in lower for m in blocked_markers)
    too_short = len(text) < 400

    if status >= 400 or soft_block or too_short:
        reason = "Could not extract a usable job description from that page."
        if soft_block:
            reason = "The page looks login-walled or blocked (common on LinkedIn)."
        elif too_short:
            reason = "Fetched page content was too short to analyze."
        return {
            "ok": False,
            "blocked": True,
            "reason": f"{reason} Paste the full job description below.",
            "text": text if len(text) > 80 else "",
            "titleHint": title_hint,
        }

    return {
        "ok": True,
        "blocked": False,
        "reason": "",
        "text": text,
        "titleHint": title_hint,
    }


def _fetch_url_text(url: str) -> str:
    result = _try_fetch_url(url)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["reason"])
    return result["text"]


@app.on_event("startup")
def on_startup() -> None:
    ensure_indexes()
    if os.environ.get("AUTO_SEED", "false").lower() in ("1", "true", "yes"):
        try:
            seed_all(force=False)
        except Exception as exc:
            logger.warning("Auto-seed failed: %s", exc)


@app.get("/health")
def health() -> dict:
    try:
        get_db().command("ping")
        mongo_ok = True
    except Exception:
        mongo_ok = False
    return {"ok": True, "mongo": mongo_ok}


@app.post("/seed")
def run_seed(force: bool = False) -> dict:
    return seed_all(force=force)


@app.get("/settings")
def get_settings() -> dict:
    from cv_shared.settings import get_app_settings

    return _serialize(get_app_settings())


@app.patch("/settings")
def patch_settings(body: SettingsPatchBody) -> dict:
    from cv_shared.settings import patch_app_settings

    payload = body.model_dump(exclude_none=True)
    return _serialize(patch_app_settings(payload))


@app.get("/candidate")
def get_candidate() -> dict:
    doc = get_db()[C.CANDIDATES].find_one({"_id": "primary-candidate"})
    if not doc:
        raise HTTPException(404, "Candidate not seeded. POST /seed first.")
    return _serialize(doc)


@app.get("/skills")
def list_skills() -> list:
    return _serialize(
        list(get_db()[C.SKILLS].find({"candidateId": "primary-candidate"}).sort("name", 1))
    )


@app.get("/projects")
def list_projects() -> list:
    return _serialize(
        list(get_db()[C.PROJECTS].find({"candidateId": "primary-candidate"}).sort("name", 1))
    )


@app.get("/work-history")
def list_work_history() -> list:
    return _serialize(
        list(
            get_db()[C.WORK_HISTORY]
            .find({"candidateId": "primary-candidate"})
            .sort("startDate", 1)
        )
    )


@app.get("/evidence")
def list_evidence() -> list:
    return _serialize(
        list(get_db()[C.EVIDENCE].find({"candidateId": "primary-candidate"}))
    )


@app.post("/jobs/fetch-url")
def fetch_job_url(body: UrlFetchBody) -> dict:
    """Probe a job URL without creating a job. Used by Analyze intake."""
    return _try_fetch_url(body.url)


@app.post("/jobs")
def create_job(body: JobCreate) -> dict:
    from cv_shared.intake.html_markdown import description_fields_from_html_or_text

    description = (body.descriptionRaw or "").strip()
    fetch_meta = None
    if not description and body.url:
        fetch_meta = _try_fetch_url(body.url)
        if not fetch_meta["ok"]:
            raise HTTPException(
                status_code=422,
                detail={
                    "blocked": True,
                    "message": fetch_meta["reason"],
                    "titleHint": fetch_meta.get("titleHint") or "",
                },
            )
        description = fetch_meta["text"]
    if not description:
        raise HTTPException(400, "Provide a job URL and/or descriptionRaw")

    fields = description_fields_from_html_or_text(description)
    description = fields["descriptionRaw"] or description
    description_md = fields.get("descriptionMarkdown")

    digest = content_hash(description)
    db = get_db()
    existing = db[C.JOBS].find_one({"contentHash": digest})
    if existing:
        return _serialize(existing)

    job_id = f"job_{digest[:16]}"
    now = datetime.now(timezone.utc).isoformat()
    title = body.title or (fetch_meta or {}).get("titleHint") or "Untitled"
    job = {
        "_id": job_id,
        "source": "manual",
        "sourceJobId": None,
        "externalId": f"manual:{digest[:16]}",
        "url": body.url,
        "sourceUrl": body.url,
        "canonicalApplyUrl": body.url,
        "title": title,
        "company": body.company or "Unknown",
        "location": body.location or "",
        "workMode": body.workMode or "unknown",
        "salary": None,
        "descriptionRaw": description,
        "descriptionMarkdown": description_md,
        "requiredSkills": [],
        "preferredSkills": [],
        "postedAt": None,
        "discoveredAt": now,
        "firstSeenAt": now,
        "lastSeenAt": now,
        "status": "new",
        "contentHash": digest,
        "discoveredBy": {"source": "manual"},
        "fingerprints": None,
        "locationAssessment": None,
        "roleAssessment": None,
    }
    try:
        from cv_shared.intake.fingerprints import build_fingerprints
        from cv_shared.intake.location import assess_location
        from cv_shared.intake.role_filter import assess_role_fit

        job["fingerprints"] = build_fingerprints(
            job["company"], job["title"], job["location"]
        )
        job["locationAssessment"] = assess_location(
            location=job["location"],
            title=job["title"],
            description=description,
            work_mode_hint=job["workMode"],
        )
        job["roleAssessment"] = assess_role_fit(
            title=job["title"],
            description=description,
        )
        if job["locationAssessment"].get("workArrangement") != "unknown":
            job["workMode"] = job["locationAssessment"]["workArrangement"]
        if not job["locationAssessment"].get("bayAreaEligible"):
            job["status"] = "out_of_area"
        elif not job["roleAssessment"].get("roleEligible"):
            job["status"] = "wrong_role"
    except Exception:
        logger.exception("manual job location/fingerprint enrichment failed")

    db[C.JOBS].insert_one(job)
    return _serialize(job)


@app.get("/jobs")
def list_jobs(
    eligible: str | None = None,
    roleEligible: str | None = None,
    applyReady: str | None = None,
    remote: str | None = None,
    invalid: str | None = None,
    status: str | None = None,
) -> list:
    """List jobs.

    - eligible: locationAssessment.bayAreaEligible
    - roleEligible: roleAssessment.roleEligible
    - applyReady: both gates true (and status not out_of_area/wrong_role)
    - remote: remote work mode or location assessment
    - invalid: union of out-of-area and wrong-role jobs
    - status: exact job status (e.g. wrong_role, out_of_area, new)
    """
    query: dict = {}
    if applyReady is not None and applyReady.lower() in ("true", "1", "yes"):
        query["locationAssessment.bayAreaEligible"] = True
        query["roleAssessment.roleEligible"] = True
        query["status"] = {"$nin": ["out_of_area", "wrong_role"]}
    elif invalid is not None and invalid.lower() in ("true", "1", "yes"):
        query["$or"] = [
            {"status": {"$in": ["out_of_area", "wrong_role"]}},
            {"locationAssessment.bayAreaEligible": False},
        ]
    elif remote is not None and remote.lower() in ("true", "1", "yes"):
        query["$or"] = [
            {"workMode": "remote"},
            {"locationAssessment.workArrangement": "remote"},
        ]
    else:
        if eligible is not None and eligible.lower() in ("true", "1", "yes"):
            query["locationAssessment.bayAreaEligible"] = True
        elif eligible is not None and eligible.lower() in ("false", "0", "no"):
            query["locationAssessment.bayAreaEligible"] = False
        if roleEligible is not None and roleEligible.lower() in ("true", "1", "yes"):
            query["roleAssessment.roleEligible"] = True
        elif roleEligible is not None and roleEligible.lower() in ("false", "0", "no"):
            query["roleAssessment.roleEligible"] = False
        if status:
            query["status"] = status.strip()

    jobs = list(get_db()[C.JOBS].find(query).sort("discoveredAt", -1))
    matches = {
        m["jobId"]: m
        for m in get_db()[C.JOB_MATCHES].find(
            {"jobId": {"$in": [j["_id"] for j in jobs]}}
        )
    }
    out = []
    for job in jobs:
        item = _serialize(job)
        item["match"] = _serialize(matches.get(job["_id"]))
        out.append(item)
    if applyReady is not None and applyReady.lower() in ("true", "1", "yes"):
        def match_score(item: dict) -> float:
            score = (item.get("match") or {}).get("score")
            return score if isinstance(score, (int, float)) else -1

        out.sort(key=match_score, reverse=True)
    return out


@app.post("/jobs/bulk-delete")
def bulk_delete_jobs(body: BulkDeleteBody) -> dict:
    """Cascade-delete many jobs (matches, packages, docs, gap aggregates, folders)."""
    from cv_shared.jobs import delete_jobs

    ids = [jid for jid in (body.jobIds or []) if isinstance(jid, str) and jid.strip()]
    if not ids:
        raise HTTPException(400, "jobIds required")
    if len(ids) > 200:
        raise HTTPException(400, "At most 200 jobs per bulk delete")
    try:
        return delete_jobs(ids)
    except Exception as exc:
        logger.exception("bulk delete failed")
        raise HTTPException(500, str(exc)) from exc


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = get_db()[C.JOBS].find_one({"_id": job_id})
    if not job:
        raise HTTPException(404, "Job not found")
    match = get_db()[C.JOB_MATCHES].find_one({"jobId": job_id})
    item = _serialize(job)
    item["match"] = _serialize(match)
    return item


@app.delete("/jobs/{job_id}")
def delete_job_endpoint(job_id: str) -> dict:
    from cv_shared.jobs import delete_job

    try:
        result = delete_job(job_id)
    except KeyError:
        raise HTTPException(404, "Job not found") from None
    except Exception as exc:
        logger.exception("delete job failed")
        raise HTTPException(500, str(exc)) from exc
    return result


@app.get("/jobs/{job_id}/match")
def get_match(job_id: str) -> dict:
    match = get_db()[C.JOB_MATCHES].find_one({"jobId": job_id})
    if not match:
        raise HTTPException(404, "Match not found — run analyze first")
    return _serialize(match)


@app.post("/jobs/{job_id}/analyze")
def post_analyze(job_id: str) -> dict:
    try:
        match = analyze_job(job_id)
    except KeyError:
        raise HTTPException(404, "Job not found") from None
    except Exception as exc:
        logger.exception("analyze failed")
        raise HTTPException(500, str(exc)) from exc
    try:
        from cv_shared.telegram import notify_apply_match

        job = get_db()[C.JOBS].find_one({"_id": job_id}) or {}
        notify_apply_match(job, match)
        # reload match for telegramNotifiedAt
        match = get_db()[C.JOB_MATCHES].find_one({"_id": match.get("_id")}) or match
    except Exception:
        logger.exception("telegram notify after analyze failed")
    return _serialize(match)


@app.post("/jobs/{job_id}/decision")
def post_decision(job_id: str, body: DecisionBody) -> dict:
    decision = body.decision.lower().strip()
    if decision not in ("apply", "save", "reject", "draft"):
        raise HTTPException(400, "decision must be apply|save|reject|draft")
    db = get_db()
    job = db[C.JOBS].find_one({"_id": job_id})
    if not job:
        raise HTTPException(404, "Job not found")
    now = datetime.now(timezone.utc).isoformat()
    status_map = {
        "apply": "interested",
        "save": "saved",
        "reject": "rejected",
        "draft": "drafted",
    }
    db[C.JOBS].update_one({"_id": job_id}, {"$set": {"status": status_map[decision]}})
    doc = {
        "_id": f"decision_{job_id}_{int(datetime.now(timezone.utc).timestamp())}",
        "jobId": job_id,
        "decision": decision,
        "note": body.note,
        "createdAt": now,
    }
    db[C.USER_DECISIONS].insert_one(doc)
    return _serialize(doc)


@app.post("/jobs/{job_id}/generate")
def post_generate(job_id: str) -> dict:
    try:
        package = generate_application_package(job_id)
    except KeyError:
        raise HTTPException(404, "Job not found") from None
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("generate failed")
        raise HTTPException(500, str(exc)) from exc
    return _serialize(package)


@app.get("/jobs/{job_id}/package")
def get_job_package(job_id: str) -> dict:
    db = get_db()
    pkg = db[C.APPLICATION_PACKAGES].find_one({"jobId": job_id})
    if not pkg:
        # Fallback: look via applications record
        app_doc = db[C.APPLICATIONS].find_one({"jobId": job_id})
        if app_doc and app_doc.get("packageId"):
            pkg = db[C.APPLICATION_PACKAGES].find_one({"_id": app_doc["packageId"]})
    if not pkg:
        raise HTTPException(404, "No package generated for this job yet")
    return _serialize(pkg)


@app.get("/jobs/{job_id}/package/files/{filename}")
def download_package_file(job_id: str, filename: str):
    from fastapi.responses import FileResponse

    # Prevent path traversal
    safe_name = Path(filename).name
    if safe_name != filename or ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "Invalid filename")

    db = get_db()
    pkg = db[C.APPLICATION_PACKAGES].find_one({"jobId": job_id})
    if not pkg:
        app_doc = db[C.APPLICATIONS].find_one({"jobId": job_id})
        if app_doc and app_doc.get("packageId"):
            pkg = db[C.APPLICATION_PACKAGES].find_one({"_id": app_doc["packageId"]})
    if not pkg:
        raise HTTPException(404, "Package not found")

    if safe_name not in (pkg.get("files") or []):
        raise HTTPException(404, "File not in package")

    folder = Path(pkg.get("folder") or "")
    path = folder / safe_name
    if not path.is_file():
        raise HTTPException(404, "File missing on disk")

    return FileResponse(
        path=str(path),
        filename=safe_name,
        media_type="application/octet-stream",
    )


@app.get("/applications")
def list_applications() -> list:
    db = get_db()
    apps = list(db[C.APPLICATIONS].find().sort("updatedAt", -1))
    out = []
    for app_doc in apps:
        item = _serialize(app_doc)
        pkg = db[C.APPLICATION_PACKAGES].find_one({"_id": app_doc.get("packageId")})
        job = db[C.JOBS].find_one({"_id": app_doc.get("jobId")})
        item["package"] = _serialize(pkg)
        item["job"] = _serialize(job)
        out.append(item)
    return out


@app.get("/applications/{app_id}")
def get_application(app_id: str) -> dict:
    app_doc = get_db()[C.APPLICATIONS].find_one({"_id": app_id})
    if not app_doc:
        raise HTTPException(404, "Application not found")
    pkg = get_db()[C.APPLICATION_PACKAGES].find_one({"_id": app_doc.get("packageId")})
    job = get_db()[C.JOBS].find_one({"_id": app_doc.get("jobId")})
    item = _serialize(app_doc)
    item["package"] = _serialize(pkg)
    item["job"] = _serialize(job)
    return item


class GapStatusBody(BaseModel):
    status: str = Field(..., description="open | learning | resolved")


@app.get("/gaps")
def list_gaps(kind: str = "all", status: str = "all") -> list:
    from cv_shared.gap_insights import list_gap_insights

    kind = (kind or "all").lower()
    status = (status or "all").lower()
    if kind not in ("all", "gap", "warning"):
        raise HTTPException(400, "kind must be all|gap|warning")
    if status not in ("all", "open", "learning", "resolved"):
        raise HTTPException(400, "status must be all|open|learning|resolved")
    return _serialize(list_gap_insights(kind=kind, status=status))


@app.patch("/gaps/{gap_id}")
def patch_gap(gap_id: str, body: GapStatusBody) -> dict:
    from cv_shared.gap_insights import update_gap_status

    try:
        doc = update_gap_status(gap_id, body.status)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not doc:
        raise HTTPException(404, "Gap insight not found")
    return _serialize(doc)


@app.post("/gaps/rebuild")
def rebuild_gaps() -> dict:
    from cv_shared.gap_insights import rebuild_gap_insights

    return rebuild_gap_insights()


@app.post("/ingest/run")
def post_ingest_run(
    analyze: bool = True,
    reprocess: bool = False,
    sources: str = "all",
) -> dict:
    """Start ingest in the background. Returns immediately.

    sources: all | gmail | greenhouse | manual (default all).
    Pass reprocess=true to clear processed-message markers first.
    Returns 409 payload (accepted=false) if an ingest is already running.
    """
    from cv_shared.intake.pipeline import start_ingest_async

    try:
        result = start_ingest_async(
            analyze=analyze, reprocess=reprocess, sources=sources
        )
    except Exception as exc:
        logger.exception("ingest start failed")
        raise HTTPException(500, str(exc)) from exc
    if result.get("conflict"):
        raise HTTPException(
            status_code=409,
            detail={
                "message": result.get("message") or "Ingest already running",
                "runId": result.get("runId"),
                "status": "running",
            },
        )
    return result


@app.get("/ingest/status")
def get_ingest_status_endpoint(runId: str | None = None) -> dict:
    from cv_shared.intake.pipeline import get_ingest_status

    doc = get_ingest_status(runId)
    if not doc:
        return {"status": "idle", "runId": None}
    return _serialize(doc)


@app.post("/ingest/cancel")
def post_ingest_cancel(force: bool = False, runId: str | None = None) -> dict:
    """Request cancel on the running ingest, or force-clear a stuck lock."""
    from cv_shared.intake.pipeline import cancel_ingest

    try:
        result = cancel_ingest(run_id=runId, force=force)
    except Exception as exc:
        logger.exception("ingest cancel failed")
        raise HTTPException(500, str(exc)) from exc
    if not result.get("found"):
        raise HTTPException(404, result.get("message") or "No running ingest")
    return result


def _kick_manual_ingest() -> dict:
    """Try to start a manual-queue ingest; return accepted/conflict payload."""
    from cv_shared.intake.pipeline import start_ingest_async

    return start_ingest_async(analyze=True, sources="manual")


@app.post("/ingest/queue")
def post_ingest_queue(body: IntakeQueueBody) -> dict:
    """Enqueue job URLs and kick manual ingest if idle."""
    from cv_shared.intake.manual_queue import enqueue_urls

    try:
        items = enqueue_urls(body.urls, description_raw=body.descriptionRaw)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("enqueue failed")
        raise HTTPException(500, str(exc)) from exc

    ingest = _kick_manual_ingest()
    return {
        "items": _serialize(items),
        "ingest": {
            "accepted": bool(ingest.get("accepted")),
            "conflict": bool(ingest.get("conflict")),
            "runId": ingest.get("runId"),
            "status": ingest.get("status"),
            "message": ingest.get("message"),
        },
    }


@app.get("/ingest/queue")
def get_ingest_queue(limit: int = 50) -> list:
    from cv_shared.intake.manual_queue import list_queue

    return _serialize(list_queue(limit=limit))


@app.post("/ingest/queue/process")
def post_ingest_queue_process() -> dict:
    """Explicitly process pending queue items (manual ingest only)."""
    ingest = _kick_manual_ingest()
    if ingest.get("conflict"):
        raise HTTPException(
            status_code=409,
            detail={
                "message": ingest.get("message") or "Ingest already running",
                "runId": ingest.get("runId"),
                "status": "running",
            },
        )
    return ingest


@app.patch("/ingest/queue/{item_id}")
def patch_ingest_queue_item(item_id: str, body: IntakeQueuePatchBody) -> dict:
    from cv_shared.intake.manual_queue import patch_queue_item

    try:
        item = patch_queue_item(item_id, description_raw=body.descriptionRaw)
    except KeyError:
        raise HTTPException(404, "Queue item not found") from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    ingest = _kick_manual_ingest()
    return {
        "item": _serialize(item),
        "ingest": {
            "accepted": bool(ingest.get("accepted")),
            "conflict": bool(ingest.get("conflict")),
            "runId": ingest.get("runId"),
            "status": ingest.get("status"),
            "message": ingest.get("message"),
        },
    }


@app.delete("/ingest/queue/{item_id}")
def delete_ingest_queue_item(item_id: str) -> dict:
    from cv_shared.intake.manual_queue import delete_queue_item

    try:
        deleted = delete_queue_item(item_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not deleted:
        raise HTTPException(404, "Queue item not found")
    return {"deleted": True, "id": item_id}


@app.get("/sources")
def list_sources() -> list:
    docs = list(
        get_db()[C.JOB_SOURCES].find({}, sort=[("priority", -1), ("name", 1)])
    )
    return _serialize(docs)


@app.post("/sources")
def create_source(body: SourceCreateBody) -> dict:
    from cv_shared.intake.greenhouse_source import probe_board_token

    name = (body.name or "").strip()
    token = (body.boardToken or "").strip().lower()
    ats = (body.ats or "greenhouse").strip().lower()
    if not name or not token:
        raise HTTPException(400, "name and boardToken are required")
    if ats != "greenhouse":
        raise HTTPException(400, "Only ats=greenhouse is supported in Stage 2B")

    probe = probe_board_token(token)
    if not probe.get("ok"):
        raise HTTPException(
            400,
            f"Invalid Greenhouse boardToken '{token}': {probe.get('error') or 'probe failed'}",
        )

    db = get_db()
    existing = db[C.JOB_SOURCES].find_one({"ats": ats, "boardToken": token})
    if existing:
        raise HTTPException(409, f"Source already exists: {existing['_id']}")

    now = datetime.now(timezone.utc).isoformat()
    source_id = f"src_{ats}_{re.sub(r'[^a-z0-9]+', '', token)[:40]}"
    # Avoid collision if id already used with different token casing historically
    if db[C.JOB_SOURCES].find_one({"_id": source_id}):
        source_id = f"{source_id}_{now[:10].replace('-', '')}"

    doc = {
        "_id": source_id,
        "name": name,
        "ats": ats,
        "boardToken": token,
        "priority": int(body.priority if body.priority is not None else 50),
        "locations": list(body.locations or []),
        "enabled": bool(body.enabled if body.enabled is not None else True),
        "careersUrl": f"https://boards.greenhouse.io/{token}",
        "lastPolledAt": None,
        "lastSuccessAt": None,
        "lastError": None,
        "lastJobCount": 0,
        "createdAt": now,
        "updatedAt": now,
    }
    db[C.JOB_SOURCES].insert_one(doc)
    return _serialize(doc)


@app.patch("/sources/{source_id}")
def patch_source(source_id: str, body: SourcePatchBody) -> dict:
    db = get_db()
    existing = db[C.JOB_SOURCES].find_one({"_id": source_id})
    if not existing:
        raise HTTPException(404, "Source not found")

    fields: dict[str, Any] = {"updatedAt": datetime.now(timezone.utc).isoformat()}
    payload = body.model_dump(exclude_none=True)
    if "enabled" in payload:
        fields["enabled"] = bool(payload["enabled"])
    if "priority" in payload:
        fields["priority"] = int(payload["priority"])
    if "locations" in payload:
        fields["locations"] = list(payload["locations"] or [])
    if "name" in payload:
        name = str(payload["name"]).strip()
        if not name:
            raise HTTPException(400, "name cannot be empty")
        fields["name"] = name

    db[C.JOB_SOURCES].update_one({"_id": source_id}, {"$set": fields})
    doc = db[C.JOB_SOURCES].find_one({"_id": source_id})
    return _serialize(doc)


@app.post("/sources/{source_id}/poll")
def poll_source(source_id: str, analyze: bool = True) -> dict:
    """Poll one Greenhouse board immediately (respects Settings master toggle)."""
    from cv_shared.intake.pipeline import start_ingest_async
    from cv_shared.settings import is_ats_source_enabled

    db = get_db()
    existing = db[C.JOB_SOURCES].find_one({"_id": source_id})
    if not existing:
        raise HTTPException(404, "Source not found")
    if existing.get("ats") != "greenhouse":
        raise HTTPException(400, "Only greenhouse sources can be polled in Stage 2B")
    if not is_ats_source_enabled("greenhouse"):
        raise HTTPException(
            400,
            "Greenhouse ingest is disabled in Settings. Enable it under ATS board ingest.",
        )
    if not existing.get("enabled", True):
        raise HTTPException(400, "Source is disabled. Enable it before polling.")

    try:
        result = start_ingest_async(
            analyze=analyze,
            sources="greenhouse",
            greenhouse_source_ids=[source_id],
        )
    except Exception as exc:
        logger.exception("source poll start failed")
        raise HTTPException(500, str(exc)) from exc
    if result.get("conflict"):
        raise HTTPException(
            status_code=409,
            detail={
                "message": result.get("message") or "Ingest already running",
                "runId": result.get("runId"),
                "status": "running",
            },
        )
    return result


@app.get("/repositories")
def list_repositories() -> list:
    docs = list(
        get_db()[C.REPOSITORIES].find({}, sort=[("fullName", 1)])
    )
    return _serialize(docs)


def _start_github_sync(
    *,
    lookback: str,
    repository_ids: list[str] | None = None,
    force: bool = False,
) -> dict:
    from cv_shared.github.pipeline import start_github_scan_async
    from cv_shared.settings import LOOKBACK_PRESETS, is_github_evidence_enabled

    if not is_github_evidence_enabled():
        raise HTTPException(
            400,
            "GitHub evidence is disabled in Settings. Enable it under GitHub evidence.",
        )
    key = (lookback or "").strip().lower()
    if key not in LOOKBACK_PRESETS:
        raise HTTPException(
            400,
            f"Invalid lookback '{lookback}'. Use one of: {', '.join(LOOKBACK_PRESETS)}",
        )
    try:
        result = start_github_scan_async(
            lookback=key,
            repository_ids=repository_ids,
            force=force,
        )
    except Exception as exc:
        logger.exception("github sync start failed")
        raise HTTPException(500, str(exc)) from exc
    if result.get("conflict"):
        raise HTTPException(
            status_code=409,
            detail={
                "message": result.get("message") or "GitHub scan already running",
                "runId": result.get("runId"),
                "status": "running",
            },
        )
    return result


@app.get("/repositories/sync/status")
def get_repositories_sync_status(runId: str | None = None) -> dict:
    from cv_shared.github.pipeline import get_github_scan_status

    doc = get_github_scan_status(runId)
    if not doc:
        return {"status": "idle", "runId": None}
    return _serialize(doc)


@app.post("/repositories/discover")
def discover_repositories_endpoint() -> dict:
    """Scan the token user's GitHub account for repos missing from the watchlist.

    New finds are stored as suggestions (approve or dismiss on Repositories).
    """
    from cv_shared.github.pipeline import discover_repositories
    from cv_shared.settings import is_github_evidence_enabled

    if not is_github_evidence_enabled():
        raise HTTPException(
            400,
            "GitHub evidence is disabled in Settings. Enable it under GitHub evidence.",
        )
    try:
        result = discover_repositories()
    except Exception as exc:
        logger.exception("repo discovery failed")
        raise HTTPException(500, str(exc)) from exc
    return result


@app.post("/repositories/sync")
def sync_repositories(body: RepositorySyncBody | None = None) -> dict:
    """Manual GitHub evidence sync for all (or selected) enabled repos."""
    payload = body or RepositorySyncBody()
    return _start_github_sync(
        lookback=payload.lookback,
        repository_ids=payload.repositoryIds,
        force=bool(payload.force),
    )


@app.post("/repositories")
def create_repository(body: RepositoryCreateBody) -> dict:
    from cv_shared.github.client import parse_full_name, probe_repository

    full_name = (body.fullName or "").strip()
    try:
        owner, repo_name = parse_full_name(full_name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    probe = probe_repository(f"{owner}/{repo_name}")
    if not probe.get("ok"):
        raise HTTPException(
            400,
            f"Invalid GitHub repository '{full_name}': "
            f"{probe.get('error') or 'probe failed'}",
        )

    db = get_db()
    canonical = probe.get("fullName") or f"{owner}/{repo_name}"
    existing = db[C.REPOSITORIES].find_one({"fullName": canonical})
    if existing:
        raise HTTPException(409, f"Repository already exists: {existing['_id']}")

    now = datetime.now(timezone.utc).isoformat()
    slug = re.sub(r"[^a-z0-9]+", "_", f"{owner}_{repo_name}".lower()).strip("_")[
        :50
    ]
    repo_id = f"repo_{slug}"
    if db[C.REPOSITORIES].find_one({"_id": repo_id}):
        repo_id = f"{repo_id}_{now[:10].replace('-', '')}"

    doc = {
        "_id": repo_id,
        "fullName": canonical,
        "defaultBranch": (
            (body.defaultBranch or "").strip()
            or probe.get("defaultBranch")
            or "main"
        ),
        "projectIds": list(body.projectIds or []),
        "enabled": bool(body.enabled if body.enabled is not None else True),
        "lastSeenCommitSha": None,
        "lastScannedAt": None,
        "lastSuccessAt": None,
        "lastError": None,
        "lastCommitCount": 0,
        "clonePath": None,
        "createdAt": now,
        "updatedAt": now,
    }
    db[C.REPOSITORIES].insert_one(doc)
    return _serialize(doc)


@app.patch("/repositories/{repo_id}")
def patch_repository(repo_id: str, body: RepositoryPatchBody) -> dict:
    db = get_db()
    existing = db[C.REPOSITORIES].find_one({"_id": repo_id})
    if not existing:
        raise HTTPException(404, "Repository not found")

    fields: dict[str, Any] = {"updatedAt": datetime.now(timezone.utc).isoformat()}
    payload = body.model_dump(exclude_none=True)
    if "enabled" in payload:
        fields["enabled"] = bool(payload["enabled"])
    if "defaultBranch" in payload:
        branch = str(payload["defaultBranch"]).strip()
        if not branch:
            raise HTTPException(400, "defaultBranch cannot be empty")
        fields["defaultBranch"] = branch
    if "projectIds" in payload:
        fields["projectIds"] = list(payload["projectIds"] or [])
    if "suggested" in payload:
        fields["suggested"] = bool(payload["suggested"])
    if "dismissed" in payload:
        fields["dismissed"] = bool(payload["dismissed"])

    db[C.REPOSITORIES].update_one({"_id": repo_id}, {"$set": fields})
    doc = db[C.REPOSITORIES].find_one({"_id": repo_id})
    return _serialize(doc)


@app.post("/repositories/{repo_id}/sync")
def sync_repository(
    repo_id: str,
    body: RepositorySyncBody | None = None,
) -> dict:
    """Manual sync for one repository."""
    db = get_db()
    existing = db[C.REPOSITORIES].find_one({"_id": repo_id})
    if not existing:
        raise HTTPException(404, "Repository not found")
    if not existing.get("enabled", True):
        raise HTTPException(400, "Repository is disabled. Enable it before syncing.")

    payload = body or RepositorySyncBody()
    return _start_github_sync(
        lookback=payload.lookback,
        repository_ids=[repo_id],
        force=bool(payload.force),
    )