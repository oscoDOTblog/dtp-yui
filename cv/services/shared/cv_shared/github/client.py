"""GitHub REST API client (PAT from secrets)."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request

logger = logging.getLogger(__name__)

API_BASE = "https://api.github.com"


def secrets_dir() -> Path:
    return Path(os.environ.get("SECRETS_DIR", "/app/secrets"))


def github_token_path() -> Path:
    return Path(
        os.environ.get("GITHUB_TOKEN_FILE") or (secrets_dir() / "github-token")
    )


def load_github_token() -> str | None:
    path = github_token_path()
    if not path.is_file():
        env_token = (os.environ.get("GITHUB_TOKEN") or "").strip()
        return env_token or None
    token = path.read_text(encoding="utf-8").strip()
    return token or None


def token_available() -> bool:
    return bool(load_github_token())


class GitHubApiError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


def _request(
    method: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    token: str | None = None,
    accept: str = "application/vnd.github+json",
) -> Any:
    tok = token if token is not None else load_github_token()
    if not tok:
        raise GitHubApiError(
            "GitHub token missing. Place a PAT in secrets/github-token "
            "or set GITHUB_TOKEN / GITHUB_TOKEN_FILE."
        )

    url = f"{API_BASE}{path}"
    if query:
        url = f"{url}?{parse.urlencode({k: v for k, v in query.items() if v is not None})}"

    headers = {
        "Accept": accept,
        "Authorization": f"Bearer {tok}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "dtp-yui-cv-github-evidence",
    }
    req = request.Request(url, headers=headers, method=method.upper())

    for attempt in range(4):
        try:
            with request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
                if not raw:
                    return None
                return json.loads(raw)
        except error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            if exc.code == 403 and "rate limit" in body.lower() and attempt < 3:
                reset = exc.headers.get("X-RateLimit-Reset")
                sleep_for = 60
                if reset:
                    try:
                        sleep_for = max(
                            5,
                            int(reset) - int(time.time()) + 1,
                        )
                        sleep_for = min(sleep_for, 120)
                    except ValueError:
                        pass
                logger.warning("GitHub rate limited; sleeping %ss", sleep_for)
                time.sleep(sleep_for)
                continue
            raise GitHubApiError(
                f"GitHub API {method} {path} failed ({exc.code}): {body or exc.reason}",
                status=exc.code,
            ) from exc
        except error.URLError as exc:
            raise GitHubApiError(f"GitHub API unreachable: {exc}") from exc

    raise GitHubApiError(f"GitHub API {method} {path} failed after retries")


def parse_full_name(full_name: str) -> tuple[str, str]:
    parts = (full_name or "").strip().strip("/").split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Invalid fullName '{full_name}' (expected owner/repo)")
    return parts[0], parts[1]


def probe_repository(full_name: str) -> dict[str, Any]:
    """Return ok/error plus repo metadata when reachable."""
    try:
        owner, repo = parse_full_name(full_name)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    try:
        data = _request("GET", f"/repos/{owner}/{repo}")
    except GitHubApiError as exc:
        return {"ok": False, "error": str(exc), "status": exc.status}
    return {
        "ok": True,
        "fullName": data.get("full_name") or f"{owner}/{repo}",
        "defaultBranch": data.get("default_branch") or "main",
        "private": bool(data.get("private")),
        "htmlUrl": data.get("html_url"),
    }


def get_repo(full_name: str) -> dict[str, Any]:
    owner, repo = parse_full_name(full_name)
    return _request("GET", f"/repos/{owner}/{repo}")


def get_branch_head_sha(full_name: str, branch: str) -> str:
    owner, repo = parse_full_name(full_name)
    data = _request("GET", f"/repos/{owner}/{repo}/commits/{parse.quote(branch)}")
    sha = (data or {}).get("sha")
    if not sha:
        raise GitHubApiError(f"Could not resolve HEAD for {full_name}@{branch}")
    return sha


def list_commits(
    full_name: str,
    *,
    branch: str,
    since: datetime | None = None,
    author: str | None = None,
    per_page: int = 100,
    max_pages: int = 10,
) -> list[dict[str, Any]]:
    """List commits on a branch, newest first."""
    owner, repo = parse_full_name(full_name)
    out: list[dict[str, Any]] = []
    page = 1
    while page <= max_pages:
        query: dict[str, Any] = {
            "sha": branch,
            "per_page": min(per_page, 100),
            "page": page,
        }
        if since is not None:
            if since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
            query["since"] = since.astimezone(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        if author:
            query["author"] = author
        batch = _request("GET", f"/repos/{owner}/{repo}/commits", query=query)
        if not isinstance(batch, list) or not batch:
            break
        out.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
    return out


def get_commit(full_name: str, sha: str) -> dict[str, Any]:
    owner, repo = parse_full_name(full_name)
    return _request("GET", f"/repos/{owner}/{repo}/commits/{sha}")


def commit_files(commit: dict[str, Any]) -> list[str]:
    files = commit.get("files") or []
    paths: list[str] = []
    for f in files:
        if isinstance(f, dict) and f.get("filename"):
            paths.append(str(f["filename"]))
    return paths


def commit_author_login(commit: dict[str, Any]) -> str:
    author = commit.get("author") or {}
    if isinstance(author, dict) and author.get("login"):
        return str(author["login"])
    commit_obj = commit.get("commit") or {}
    author_obj = commit_obj.get("author") or {}
    return str(author_obj.get("name") or "").strip()


def commit_message(commit: dict[str, Any]) -> str:
    commit_obj = commit.get("commit") or {}
    return str(commit_obj.get("message") or "").strip()


def commit_date(commit: dict[str, Any]) -> str | None:
    commit_obj = commit.get("commit") or {}
    author_obj = commit_obj.get("author") or {}
    return author_obj.get("date") or (commit_obj.get("committer") or {}).get("date")
