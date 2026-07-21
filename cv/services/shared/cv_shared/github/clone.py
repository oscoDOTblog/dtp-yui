"""Shallow clone helpers for repository-cache bootstrap."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from .client import load_github_token, parse_full_name

logger = logging.getLogger(__name__)


def repository_cache_dir() -> Path:
    return Path(os.environ.get("REPOSITORY_CACHE_DIR", "/app/repository-cache"))


def clone_rel_path(full_name: str) -> str:
    owner, repo = parse_full_name(full_name)
    safe = f"{owner}__{repo}".replace("/", "_")
    return safe


def clone_abs_path(full_name: str) -> Path:
    return repository_cache_dir() / clone_rel_path(full_name)


def _auth_clone_url(full_name: str) -> str:
    owner, repo = parse_full_name(full_name)
    token = load_github_token()
    if token:
        # x-access-token works for classic and fine-grained PATs
        return f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
    return f"https://github.com/{owner}/{repo}.git"


def ensure_shallow_clone(
    full_name: str,
    *,
    branch: str = "main",
) -> dict:
    """Shallow clone or fetch. Returns {ok, clonePath, error?}."""
    cache_root = repository_cache_dir()
    cache_root.mkdir(parents=True, exist_ok=True)
    rel = clone_rel_path(full_name)
    dest = cache_root / rel
    url = _auth_clone_url(full_name)

    try:
        if (dest / ".git").is_dir():
            subprocess.run(
                ["git", "-C", str(dest), "fetch", "--depth", "1", "origin", branch],
                check=True,
                capture_output=True,
                text=True,
                timeout=180,
            )
            subprocess.run(
                ["git", "-C", str(dest), "checkout", "-f", "FETCH_HEAD"],
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
        else:
            if dest.exists():
                # Incomplete prior attempt
                import shutil

                shutil.rmtree(dest)
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    branch,
                    "--single-branch",
                    url,
                    str(dest),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
        return {"ok": True, "clonePath": rel, "absPath": str(dest)}
    except FileNotFoundError:
        return {"ok": False, "error": "git binary not found in container"}
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or str(exc)).strip()[:500]
        # Redact token if it leaked into the URL in error text
        token = load_github_token()
        if token and token in err:
            err = err.replace(token, "***")
        logger.warning("Shallow clone failed for %s: %s", full_name, err)
        return {"ok": False, "error": err or "git clone failed"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "git clone timed out"}


def detect_bootstrap_signals(clone_path: Path | str) -> dict:
    """Scan a cloned tree for ladder-relevant signals (tests, CI, manifests)."""
    root = Path(clone_path)
    signals: dict = {
        "hasTests": False,
        "hasCi": False,
        "hasDockerfile": False,
        "manifests": [],
        "suggestedFloor": "implemented",
    }
    if not root.is_dir():
        return signals

    test_markers = ("test", "tests", "__tests__", "spec", "specs")
    ci_markers = (
        ".github/workflows",
        ".gitlab-ci.yml",
        "Jenkinsfile",
        ".circleci",
    )
    manifests = (
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "Cargo.toml",
        "go.mod",
        "Podfile",
        "build.gradle",
        "build.gradle.kts",
        "Package.swift",
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "serverless.yml",
        "serverless.yaml",
    )

    for dirpath, dirnames, filenames in os.walk(root):
        # Skip .git internals
        if ".git" in dirnames:
            dirnames.remove(".git")
        rel = Path(dirpath).relative_to(root).as_posix()
        lower_parts = {p.lower() for p in Path(rel).parts if p != "."}
        if lower_parts & set(test_markers) or any(
            f.lower().startswith("test_") or f.lower().endswith("_test.py")
            or f.lower().endswith(".test.ts")
            or f.lower().endswith(".test.tsx")
            or f.lower().endswith(".spec.ts")
            for f in filenames
        ):
            signals["hasTests"] = True
        for name in filenames:
            if name in manifests and name not in signals["manifests"]:
                signals["manifests"].append(name)
            if name == "Dockerfile":
                signals["hasDockerfile"] = True

    for marker in ci_markers:
        if (root / marker).exists():
            signals["hasCi"] = True
            break

    floor = "implemented"
    if signals["hasTests"]:
        floor = "tested"
    if signals["hasCi"] or signals["hasDockerfile"]:
        # Deployed is a stretch from CI alone; keep tested unless both present
        if signals["hasTests"] and signals["hasCi"]:
            floor = "tested"
    signals["suggestedFloor"] = floor
    return signals
