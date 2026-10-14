"""GitHub evidence scan orchestration."""

from __future__ import annotations

import logging
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .. import collections as C
from ..db import get_db
from ..matching import analyze_job
from ..settings import (
    LOOKBACK_PRESETS,
    get_app_settings,
    is_github_evidence_enabled,
)
from . import client as gh
from .analyze import classify_commit, clamp_level, ladder_rank
from .clone import detect_bootstrap_signals, ensure_shallow_clone

logger = logging.getLogger(__name__)

_scan_lock = threading.Lock()

LOOKBACK_DELTAS = {
    "1d": timedelta(days=1),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
    "365d": timedelta(days=365),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def parse_lookback(lookback: str | None) -> tuple[str, datetime | None]:
    """Return (preset, since_dt). since_dt is None for 'all'."""
    key = (lookback or "7d").strip().lower()
    if key not in LOOKBACK_PRESETS:
        key = "7d"
    if key == "all":
        return key, None
    return key, _now_dt() - LOOKBACK_DELTAS[key]


def _patch_run(run_id: str, fields: dict[str, Any]) -> None:
    get_db()[C.SYSTEM_RUNS].update_one({"_id": run_id}, {"$set": fields})


def get_running_github_scan() -> dict[str, Any] | None:
    return get_db()[C.SYSTEM_RUNS].find_one(
        {"type": "githubScan", "status": "running"}
    )


def get_github_scan_status(run_id: str | None = None) -> dict[str, Any] | None:
    db = get_db()
    if run_id:
        return db[C.SYSTEM_RUNS].find_one({"_id": run_id})
    return db[C.SYSTEM_RUNS].find_one(
        {"type": "githubScan"},
        sort=[("startedAt", -1)],
    )


def _repo_id_slug(full_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", full_name.lower()).strip("_")[:50]
    return f"repo_{slug or uuid.uuid4().hex[:8]}"


def discover_repositories() -> dict[str, Any]:
    """Find repos on the token user's account missing from cv_repositories.

    New finds are inserted as suggestions (suggested=True, enabled=False)
    awaiting manual approval. Forks and archived repos are skipped. Repos
    already present in any state (including dismissed) are never re-suggested.
    """
    db = get_db()
    existing = {
        (doc.get("fullName") or "").lower()
        for doc in db[C.REPOSITORIES].find({}, {"fullName": 1})
    }
    remote = gh.list_viewer_repos()
    now = _now()
    suggested = 0

    for repo in remote:
        full_name = (repo.get("full_name") or "").strip()
        if not full_name or full_name.lower() in existing:
            continue
        if repo.get("fork") or repo.get("archived"):
            continue

        repo_id = _repo_id_slug(full_name)
        if db[C.REPOSITORIES].find_one({"_id": repo_id}):
            repo_id = f"{repo_id}_{now[:10].replace('-', '')}"

        db[C.REPOSITORIES].insert_one(
            {
                "_id": repo_id,
                "fullName": full_name,
                "defaultBranch": repo.get("default_branch") or "main",
                "projectIds": [],
                "enabled": False,
                "suggested": True,
                "dismissed": False,
                "discoveredAt": now,
                "lastSeenCommitSha": None,
                "lastScannedAt": None,
                "lastSuccessAt": None,
                "lastError": None,
                "lastCommitCount": 0,
                "clonePath": None,
                "createdAt": now,
                "updatedAt": now,
            }
        )
        existing.add(full_name.lower())
        suggested += 1

    return {"checked": len(remote), "suggested": suggested}


def bump_profile_version() -> int:
    """Increment candidate.profileVersion; return new value."""
    db = get_db()
    candidate = db[C.CANDIDATES].find_one({"_id": "primary-candidate"})
    current = int((candidate or {}).get("profileVersion") or 1)
    nxt = current + 1
    db[C.CANDIDATES].update_one(
        {"_id": "primary-candidate"},
        {"$set": {"profileVersion": nxt, "updatedAt": _now()}},
        upsert=False,
    )
    return nxt


def _skill_id_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40]
    return f"skill_{slug or uuid.uuid4().hex[:8]}"


def _apply_evidence_writes(
    *,
    repo: dict[str, Any],
    sha: str,
    items: list[dict[str, Any]],
    skills_cache: list[dict[str, Any]],
) -> dict[str, int]:
    """Upsert evidence + monotonic skill upgrades. Returns change counts."""
    db = get_db()
    now = _now()
    evidence_created = 0
    skills_upgraded = 0
    skills_created = 0
    project_ids = list(repo.get("projectIds") or [])

    for item in items:
        skill_id = item.get("skillId")
        skill_name = item.get("skillName") or "Unknown"
        level = clamp_level(item.get("evidenceLevel"))
        claim = item.get("claim") or ""

        if not skill_id:
            # Create draft skill
            skill_id = _skill_id_slug(skill_name)
            existing = db[C.SKILLS].find_one({"_id": skill_id})
            n = 0
            while existing and (existing.get("name") or "").lower() != skill_name.lower():
                n += 1
                skill_id = f"{_skill_id_slug(skill_name)}_{n}"
                existing = db[C.SKILLS].find_one({"_id": skill_id})
            if not existing:
                new_skill = {
                    "_id": skill_id,
                    "candidateId": "primary-candidate",
                    "name": skill_name,
                    "category": "other",
                    "confidence": 0.5,
                    "evidenceLevel": level,
                    "approvedForResume": False,
                    "projectIds": list(project_ids),
                    "workHistoryIds": [],
                    "evidenceIds": [],
                    "aliases": [],
                    "updatedAt": now,
                }
                db[C.SKILLS].insert_one(new_skill)
                skills_cache.append(new_skill)
                skills_created += 1
            else:
                skill_id = existing["_id"]

        skill = db[C.SKILLS].find_one({"_id": skill_id})
        if not skill:
            continue

        evidence_id = f"evidence_gh_{repo['_id']}_{sha[:10]}_{skill_id}"
        if not db[C.EVIDENCE].find_one({"_id": evidence_id}):
            ev_doc = {
                "_id": evidence_id,
                "candidateId": "primary-candidate",
                "claim": claim,
                "skillIds": [skill_id],
                "projectIds": list(project_ids),
                "workHistoryIds": [],
                "source": "github",
                "repositoryId": repo["_id"],
                "commitSha": sha,
                "approvedForResume": False,
                "createdAt": now,
                "updatedAt": now,
            }
            db[C.EVIDENCE].insert_one(ev_doc)
            evidence_created += 1
            add_to_set: dict[str, Any] = {"evidenceIds": evidence_id}
            if project_ids:
                add_to_set["projectIds"] = {"$each": project_ids}
            db[C.SKILLS].update_one(
                {"_id": skill_id},
                {"$addToSet": add_to_set, "$set": {"updatedAt": now}},
            )

        current_level = skill.get("evidenceLevel") or "implemented"
        if ladder_rank(level) > ladder_rank(current_level):
            db[C.SKILLS].update_one(
                {"_id": skill_id},
                {"$set": {"evidenceLevel": level, "updatedAt": now}},
            )
            skills_upgraded += 1
            skill["evidenceLevel"] = level
            # refresh cache entry
            for i, s in enumerate(skills_cache):
                if s.get("_id") == skill_id:
                    skills_cache[i] = {**s, "evidenceLevel": level}
                    break

    if project_ids and (evidence_created or skills_upgraded or skills_created):
        db[C.PROJECTS].update_many(
            {"_id": {"$in": project_ids}},
            {"$set": {"updatedAt": now}},
        )

    return {
        "evidenceCreated": evidence_created,
        "skillsUpgraded": skills_upgraded,
        "skillsCreated": skills_created,
    }


def rescore_stale_matches(profile_version: int) -> int:
    """Re-analyze jobs whose match was stamped with an older profileVersion."""
    db = get_db()
    stale = list(
        db[C.JOB_MATCHES].find(
            {"profileVersion": {"$lt": profile_version}},
            {"jobId": 1},
        )
    )
    rescored = 0
    for match in stale:
        job_id = match.get("jobId")
        if not job_id:
            continue
        job = db[C.JOBS].find_one({"_id": job_id})
        if not job or job.get("status") in ("out_of_area", "wrong_role"):
            continue
        try:
            analyze_job(job_id)
            rescored += 1
        except Exception as exc:
            logger.warning("Rescore failed for %s: %s", job_id, exc)
    return rescored


def _update_repo_scan(
    repo_id: str,
    *,
    error: str | None = None,
    head_sha: str | None = None,
    commit_count: int | None = None,
    clone_path: str | None = None,
) -> None:
    now = _now()
    fields: dict[str, Any] = {"lastScannedAt": now, "updatedAt": now}
    if error is not None:
        fields["lastError"] = error[:500]
    else:
        fields["lastError"] = None
        fields["lastSuccessAt"] = now
        if head_sha:
            fields["lastSeenCommitSha"] = head_sha
        if commit_count is not None:
            fields["lastCommitCount"] = commit_count
        if clone_path:
            fields["clonePath"] = clone_path
    get_db()[C.REPOSITORIES].update_one({"_id": repo_id}, {"$set": fields})


def _author_matches(commit: dict[str, Any], author_logins: list[str]) -> bool:
    if not author_logins:
        return True
    login = (gh.commit_author_login(commit) or "").lower()
    allowed = {a.lower() for a in author_logins}
    if login in allowed:
        return True
    # Also check commit author email/name loosely against logins
    commit_obj = commit.get("commit") or {}
    name = str((commit_obj.get("author") or {}).get("name") or "").lower()
    return any(a in name for a in allowed)


def _scan_one_repo(
    repo: dict[str, Any],
    *,
    lookback_key: str,
    since: datetime | None,
    force: bool,
    cron_mode: bool,
    author_logins: list[str],
    skills_cache: list[dict[str, Any]],
    publish: Callable[[], None],
    summary: dict[str, Any],
) -> None:
    full_name = repo.get("fullName") or ""
    branch = (repo.get("defaultBranch") or "main").strip() or "main"
    summary["currentRepo"] = full_name
    publish()

    try:
        head_sha = gh.get_branch_head_sha(full_name, branch)
    except Exception as exc:
        _update_repo_scan(repo["_id"], error=str(exc))
        summary["reposFailed"] += 1
        summary["errors"].append(f"{full_name}: {exc}")
        publish()
        return

    if (
        cron_mode
        and not force
        and repo.get("lastSeenCommitSha")
        and repo.get("lastSeenCommitSha") == head_sha
    ):
        summary["reposSkippedUnchanged"] += 1
        _update_repo_scan(
            repo["_id"],
            head_sha=head_sha,
            commit_count=0,
        )
        publish()
        return

    bootstrap_floor = None
    clone_path = repo.get("clonePath")
    first_scan = not repo.get("lastSuccessAt")
    if first_scan or not clone_path:
        clone_result = ensure_shallow_clone(full_name, branch=branch)
        if clone_result.get("ok"):
            clone_path = clone_result.get("clonePath")
            signals = detect_bootstrap_signals(clone_result.get("absPath") or "")
            bootstrap_floor = signals.get("suggestedFloor")
            summary["clones"] = summary.get("clones", 0) + 1
        else:
            summary["cloneErrors"] = summary.get("cloneErrors", 0) + 1
            if clone_result.get("error"):
                logger.warning(
                    "Clone bootstrap skipped for %s: %s",
                    full_name,
                    clone_result["error"],
                )

    # Fetch commits: for author filter, GitHub API supports one author at a time
    commits: list[dict[str, Any]] = []
    try:
        if author_logins:
            seen_shas: set[str] = set()
            for login in author_logins:
                batch = gh.list_commits(
                    full_name,
                    branch=branch,
                    since=since,
                    author=login,
                )
                for c in batch:
                    sha = c.get("sha")
                    if sha and sha not in seen_shas:
                        seen_shas.add(sha)
                        commits.append(c)
        else:
            commits = gh.list_commits(full_name, branch=branch, since=since)
    except Exception as exc:
        _update_repo_scan(repo["_id"], error=str(exc))
        summary["reposFailed"] += 1
        summary["errors"].append(f"{full_name}: {exc}")
        publish()
        return

    db = get_db()
    processed = 0
    profile_dirty = False

    for commit in commits:
        sha = commit.get("sha")
        if not sha:
            continue
        if not _author_matches(commit, author_logins):
            continue

        scan_id = f"{repo['_id']}:{sha}"
        if not force and db[C.REPOSITORY_SCANS].find_one({"_id": scan_id}):
            continue

        try:
            detail = gh.get_commit(full_name, sha)
        except Exception as exc:
            summary["errors"].append(f"{full_name}@{sha[:7]}: {exc}")
            continue

        message = gh.commit_message(detail)
        files = gh.commit_files(detail)
        committed_at = gh.commit_date(detail)

        items = classify_commit(
            full_name=full_name,
            message=message,
            files=files,
            known_skills=skills_cache,
            bootstrap_floor=bootstrap_floor if first_scan else None,
        )

        write_stats = _apply_evidence_writes(
            repo=repo,
            sha=sha,
            items=items,
            skills_cache=skills_cache,
        )
        if (
            write_stats["evidenceCreated"]
            or write_stats["skillsUpgraded"]
            or write_stats["skillsCreated"]
        ):
            profile_dirty = True
            summary["evidenceCreated"] += write_stats["evidenceCreated"]
            summary["skillsUpgraded"] += write_stats["skillsUpgraded"]
            summary["skillsCreated"] += write_stats["skillsCreated"]

        db[C.REPOSITORY_SCANS].replace_one(
            {"_id": scan_id},
            {
                "_id": scan_id,
                "repositoryId": repo["_id"],
                "sha": sha,
                "committedAt": committed_at,
                "message": message[:2000],
                "files": files[:100],
                "extracted": items,
                "createdAt": _now(),
            },
            upsert=True,
        )
        processed += 1
        summary["commitsProcessed"] += 1
        publish()

    _update_repo_scan(
        repo["_id"],
        head_sha=head_sha,
        commit_count=processed,
        clone_path=clone_path,
    )
    summary["reposScanned"] += 1
    if profile_dirty:
        summary["profileDirty"] = True
    publish()


def run_github_scan(
    *,
    lookback: str | None = None,
    repository_ids: list[str] | None = None,
    force: bool = False,
    cron_mode: bool = False,
    run_id: str | None = None,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Scan configured GitHub repos for evidence.

    lookback: required for manual; cron_mode uses since-last-sha / defaultLookback.
    cron_mode: skip repos whose HEAD SHA matches lastSeenCommitSha.
    """
    started = _now()
    db = get_db()
    run_id = run_id or f"githubScan_{uuid.uuid4().hex[:16]}"
    app_settings = get_app_settings()
    github_cfg = app_settings.get("githubEvidence") or {}

    summary: dict[str, Any] = {
        "runId": run_id,
        "status": "running",
        "startedAt": started,
        "finishedAt": None,
        "cronMode": cron_mode,
        "lookback": None,
        "reposTotal": 0,
        "reposScanned": 0,
        "reposSkippedUnchanged": 0,
        "reposFailed": 0,
        "commitsProcessed": 0,
        "evidenceCreated": 0,
        "skillsUpgraded": 0,
        "skillsCreated": 0,
        "rescored": 0,
        "profileVersion": None,
        "profileDirty": False,
        "currentRepo": "",
        "errors": [],
        "clones": 0,
        "cloneErrors": 0,
        "reposSuggested": 0,
    }

    def publish() -> None:
        payload = {k: v for k, v in summary.items() if k != "status"}
        _patch_run(
            run_id,
            {
                "status": summary["status"],
                "summary": payload,
                "errors": summary.get("errors") or [],
                "currentRepo": summary.get("currentRepo") or "",
                "reposScanned": summary.get("reposScanned", 0),
                "commitsProcessed": summary.get("commitsProcessed", 0),
            },
        )
        if progress_cb:
            progress_cb(summary)

    if not is_github_evidence_enabled(app_settings):
        summary["status"] = "completed"
        summary["finishedAt"] = _now()
        summary["errors"].append("GitHub evidence is disabled in Settings")
        publish()
        return summary

    if not gh.token_available():
        summary["status"] = "failed"
        summary["finishedAt"] = _now()
        summary["errors"].append(
            "GitHub token missing (secrets/github-token or GITHUB_TOKEN)"
        )
        publish()
        return summary

    if github_cfg.get("discoverRepos", True):
        try:
            discovery = discover_repositories()
            summary["reposSuggested"] = discovery.get("suggested", 0)
        except Exception as exc:
            logger.warning("Repo discovery failed: %s", exc)
            summary["errors"].append(f"discover: {exc}")
        publish()

    if cron_mode and lookback is None:
        lookback_key = (github_cfg.get("defaultLookback") or "7d").strip().lower()
        if lookback_key not in LOOKBACK_PRESETS:
            lookback_key = "7d"
        lookback_key, since = parse_lookback(lookback_key)
    else:
        lookback_key, since = parse_lookback(lookback)
    summary["lookback"] = lookback_key

    query: dict[str, Any] = {"enabled": True, "suggested": {"$ne": True}}
    if repository_ids:
        query["_id"] = {"$in": list(repository_ids)}
    repos = list(db[C.REPOSITORIES].find(query, sort=[("fullName", 1)]))
    summary["reposTotal"] = len(repos)
    publish()

    author_logins = list(github_cfg.get("authorLogins") or ["oscoDOTblog"])
    skills_cache = list(
        db[C.SKILLS].find({"candidateId": "primary-candidate"})
    )

    for repo in repos:
        # Cron with lastSeenCommitSha: still list commits since that point via
        # SHA skip at HEAD; when first scan use lookback since.
        repo_since = since
        if cron_mode and repo.get("lastSeenCommitSha") and since is not None:
            # Prefer lookback window; HEAD skip already handled inside _scan_one_repo
            pass
        try:
            _scan_one_repo(
                repo,
                lookback_key=lookback_key,
                since=repo_since,
                force=force,
                cron_mode=cron_mode,
                author_logins=author_logins,
                skills_cache=skills_cache,
                publish=publish,
                summary=summary,
            )
        except Exception as exc:
            logger.exception("Repo scan crashed for %s", repo.get("fullName"))
            summary["reposFailed"] += 1
            summary["errors"].append(f"{repo.get('fullName')}: {exc}")
            _update_repo_scan(repo["_id"], error=str(exc))
            publish()

    if summary.get("profileDirty"):
        new_version = bump_profile_version()
        summary["profileVersion"] = new_version
        summary["rescored"] = rescore_stale_matches(new_version)
        publish()
    else:
        candidate = db[C.CANDIDATES].find_one({"_id": "primary-candidate"})
        summary["profileVersion"] = int(
            (candidate or {}).get("profileVersion") or 1
        )

    summary["currentRepo"] = ""
    summary["status"] = "completed"
    summary["finishedAt"] = _now()
    publish()
    logger.info("GitHub scan complete: %s", summary)
    return summary


def start_github_scan_async(
    *,
    lookback: str,
    repository_ids: list[str] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Single-flight background scan for the API. Returns immediately."""
    with _scan_lock:
        running = get_running_github_scan()
        if running:
            return {
                "accepted": False,
                "conflict": True,
                "runId": running.get("_id"),
                "status": "running",
                "message": "GitHub scan already running",
            }

        lookback_key, _ = parse_lookback(lookback)
        run_id = f"githubScan_{uuid.uuid4().hex[:16]}"
        get_db()[C.SYSTEM_RUNS].insert_one(
            {
                "_id": run_id,
                "type": "githubScan",
                "status": "running",
                "startedAt": _now(),
                "lookback": lookback_key,
                "reposScanned": 0,
                "commitsProcessed": 0,
                "currentRepo": "Starting…",
                "errors": [],
                "summary": {},
            }
        )

        def _worker() -> None:
            try:
                run_github_scan(
                    lookback=lookback_key,
                    repository_ids=repository_ids,
                    force=force,
                    cron_mode=False,
                    run_id=run_id,
                )
            except Exception:
                logger.exception("background github scan failed")
                _patch_run(
                    run_id,
                    {
                        "status": "failed",
                        "finishedAt": _now(),
                        "errors": ["background github scan crashed"],
                    },
                )

        thread = threading.Thread(
            target=_worker, name=f"github-scan-{run_id}", daemon=True
        )
        thread.start()
        return {
            "accepted": True,
            "conflict": False,
            "runId": run_id,
            "status": "running",
            "lookback": lookback_key,
        }
