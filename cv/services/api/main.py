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


class DecisionBody(BaseModel):
    decision: str = Field(..., description="apply | save | reject | draft")
    note: Optional[str] = None


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
        "url": body.url,
        "title": title,
        "company": body.company or "Unknown",
        "location": body.location or "",
        "workMode": body.workMode or "unknown",
        "salary": None,
        "descriptionRaw": description,
        "requiredSkills": [],
        "preferredSkills": [],
        "postedAt": None,
        "discoveredAt": now,
        "status": "new",
        "contentHash": digest,
    }
    db[C.JOBS].insert_one(job)
    return _serialize(job)


@app.get("/jobs")
def list_jobs() -> list:
    jobs = list(get_db()[C.JOBS].find().sort("discoveredAt", -1))
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
    return out


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
