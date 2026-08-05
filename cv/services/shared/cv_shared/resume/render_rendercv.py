"""Map TailorPayload → RenderCV YAML and produce PDF."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .achievements import Achievement, catalog_by_id
from .tailor import TailorPayload

logger = logging.getLogger(__name__)


def build_rendercv_data(
    *,
    candidate: dict,
    skills: list[dict],
    work_history: list[dict],
    projects: list[dict],
    catalog: list[Achievement],
    payload: TailorPayload,
    template_id: str = "classic",
) -> dict[str, Any]:
    by_id = catalog_by_id(catalog)
    rewrite = payload.rewrite_map()
    skill_by_id = {s["_id"]: s for s in skills if s.get("_id")}
    work_by_id = {w["_id"]: w for w in work_history if w.get("_id")}
    project_by_id = {p["_id"]: p for p in projects if p.get("_id")}

    sections: dict[str, Any] = {}

    if payload.summary:
        sections["summary"] = [payload.summary]

    highlights = list(getattr(payload, "highlights", None) or [])
    if highlights:
        sections["highlights"] = [h.text for h in highlights]

    skill_groups = getattr(payload, "skillsGrouped", None) or {}
    if skill_groups:
        sections["skills"] = []
        for cat, ids in skill_groups.items():
            names = [
                skill_by_id[sid]["name"]
                for sid in ids
                if sid in skill_by_id and skill_by_id[sid].get("name")
            ]
            if names:
                sections["skills"].append(
                    {"label": cat, "details": ", ".join(names)}
                )
    else:
        skill_names = [
            skill_by_id[sid]["name"]
            for sid in payload.selectedSkillIds
            if sid in skill_by_id and skill_by_id[sid].get("name")
        ]
        if skill_names:
            # Group roughly by category for OneLineEntry sections
            by_cat: dict[str, list[str]] = {}
            for sid in payload.selectedSkillIds:
                skill = skill_by_id.get(sid)
                if not skill or not skill.get("name"):
                    continue
                cat = str(skill.get("category") or "skills").replace("_", " ").title()
                by_cat.setdefault(cat, []).append(skill["name"])
            sections["skills"] = [
                {"label": cat, "details": ", ".join(names)}
                for cat, names in by_cat.items()
            ]

    experience_entries: list[dict[str, Any]] = []
    work_groups: dict[str, list[str]] = {}
    work_order: list[str] = []
    for aid in payload.selectedAchievementIds:
        ach = by_id.get(aid)
        if not ach or ach.kind != "work":
            continue
        if ach.parentId not in work_groups:
            work_groups[ach.parentId] = []
            work_order.append(ach.parentId)
        work_groups[ach.parentId].append(rewrite.get(aid) or ach.statement)

    for wid in work_order:
        role = work_by_id.get(wid) or {}
        entry: dict[str, Any] = {
            "company": role.get("company") or "Employer",
            "position": role.get("title") or "Software Engineer",
            "highlights": work_groups[wid],
        }
        if role.get("companyLocation"):
            entry["location"] = role["companyLocation"]
        if role.get("startDate"):
            entry["start_date"] = _rendercv_date(role["startDate"])
        if role.get("endDate"):
            entry["end_date"] = _rendercv_date(role["endDate"])
        else:
            entry["end_date"] = "present"
        experience_entries.append(entry)
    if experience_entries:
        sections["experience"] = experience_entries

    project_entries: list[dict[str, Any]] = []
    project_groups: dict[str, list[str]] = {}
    project_order: list[str] = []
    for aid in payload.selectedAchievementIds:
        ach = by_id.get(aid)
        if not ach or ach.kind != "project":
            continue
        if ach.parentId not in project_groups:
            project_groups[ach.parentId] = []
            project_order.append(ach.parentId)
        project_groups[ach.parentId].append(rewrite.get(aid) or ach.statement)

    for pid in project_order:
        project = project_by_id.get(pid) or {}
        entry = {
            "name": project.get("name") or pid,
            "highlights": project_groups[pid],
        }
        if project.get("startDate"):
            entry["start_date"] = _rendercv_date(project["startDate"])
        if project.get("summary"):
            entry["summary"] = project["summary"]
        project_entries.append(entry)
    if project_entries:
        sections["projects"] = project_entries

    edu = (candidate.get("education") or [{}])[0]
    if edu and (edu.get("institution") or edu.get("school")):
        edu_entry: dict[str, Any] = {
            "institution": edu.get("institution") or edu.get("school") or "University",
            "area": edu.get("school") or edu.get("degree") or "Computer Science",
        }
        if edu.get("degree"):
            edu_entry["degree"] = edu["degree"]
        if edu.get("location"):
            edu_entry["location"] = edu["location"]
        if edu.get("graduatedAt"):
            edu_entry["end_date"] = _rendercv_date(edu["graduatedAt"])
        sections["education"] = [edu_entry]

    # Reorder sections per payload when possible
    ordered_sections: dict[str, Any] = {}
    for key in payload.sectionOrder:
        mapped = {
            "summary": "summary",
            "highlights": "highlights",
            "skills": "skills",
            "experience": "experience",
            "projects": "projects",
            "education": "education",
        }.get(key)
        if mapped and mapped in sections:
            ordered_sections[mapped] = sections.pop(mapped)
    for key, value in sections.items():
        ordered_sections[key] = value

    cv: dict[str, Any] = {
        "name": candidate.get("name") or "Candidate",
        "location": candidate.get("location") or None,
        "email": candidate.get("email") or None,
        "sections": ordered_sections,
    }
    if payload.targetRole:
        cv["headline"] = payload.targetRole

    social = []
    linkedin = _social_username(candidate.get("linkedin"), "linkedin")
    if linkedin:
        social.append({"network": "LinkedIn", "username": linkedin})
    github = _social_username(candidate.get("github"), "github")
    if github:
        social.append({"network": "GitHub", "username": github})
    if social:
        cv["social_networks"] = social

    phone = candidate.get("phone")
    if phone:
        cv["phone"] = str(phone)

    # Drop None values at top level
    cv = {k: v for k, v in cv.items() if v is not None}

    theme = (template_id or "classic").strip().lower()
    if theme not in ("classic", "sb2nov", "engineeringresumes", "moderncv", "markdowncv"):
        theme = "classic"

    return {
        "cv": cv,
        "design": {"theme": theme},
        "settings": {
            "render_command": {
                "dont_generate_html": True,
                "dont_generate_markdown": True,
                "dont_generate_png": True,
                "output_folder_name": "rendercv_output",
            }
        },
    }


def write_rendercv_yaml(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from ruamel.yaml import YAML

        yaml = YAML()
        yaml.default_flow_style = False
        with path.open("w", encoding="utf-8") as fh:
            yaml.dump(data, fh)
    except ImportError:
        import yaml  # type: ignore

        path.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )


def render_pdf_with_rendercv(
    yaml_path: Path,
    pdf_path: Path,
) -> Path:
    """Run `rendercv render` and copy the resulting PDF to pdf_path."""
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rendercv_") as tmp:
        tmp_dir = Path(tmp)
        local_yaml = tmp_dir / "resume.yaml"
        shutil.copy2(yaml_path, local_yaml)
        cmd = ["rendercv", "render", str(local_yaml)]
        try:
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(tmp_dir),
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "rendercv CLI not installed; pip install 'rendercv[full]'"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("rendercv timed out") from exc

        if result.returncode != 0:
            raise RuntimeError(
                f"rendercv failed ({result.returncode}): "
                f"{(result.stderr or result.stdout or '')[:800]}"
            )

        produced = list(tmp_dir.rglob("*.pdf"))
        if not produced:
            raise RuntimeError(
                f"rendercv produced no PDF: {(result.stdout or '')[:400]}"
            )
        shutil.copy2(produced[0], pdf_path)
    return pdf_path


def _rendercv_date(value: str) -> str:
    """Normalize to YYYY-MM or YYYY when possible."""
    text = (value or "").strip()
    if not text:
        return text
    if re.match(r"^\d{4}-\d{2}$", text):
        return text
    if re.match(r"^\d{4}$", text):
        return text
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return text[:7]
    return text


def _social_username(url_or_user: str | None, network: str) -> str | None:
    if not url_or_user:
        return None
    text = str(url_or_user).strip().rstrip("/")
    if not text:
        return None
    if "://" not in text and "/" not in text:
        return text.lstrip("@")
    try:
        parsed = urlparse(text if "://" in text else f"https://{text}")
        parts = [p for p in (parsed.path or "").split("/") if p]
        if parts:
            return parts[-1]
    except Exception:
        pass
    return text
