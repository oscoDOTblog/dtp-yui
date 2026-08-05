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

from .achievements import Achievement
from .layout import build_resume_layout
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
    layout = build_resume_layout(
        candidate=candidate,
        skills=skills,
        work_history=work_history,
        projects=projects,
        catalog=catalog,
        payload=payload,
    )

    sections: dict[str, Any] = {}

    if layout.summary:
        sections["summary"] = [layout.summary]

    if layout.highlights:
        sections["highlights"] = list(layout.highlights)

    if layout.coreExpertise:
        sections["skills"] = [
            {"label": "Core Expertise", "details": layout.coreExpertise.replace(" • ", ", ")}
        ]
        for line in layout.technologyLines:
            if ":" in line:
                label, details = line.split(":", 1)
                sections["skills"].append(
                    {"label": label.strip(), "details": details.strip()}
                )
            elif line.strip():
                sections["skills"].append({"label": "Tools", "details": line.strip()})

    experience_entries: list[dict[str, Any]] = []
    for emp in layout.employers:
        if not emp.titles:
            continue
        newest = emp.titles[0]
        # Stack all titles into the position field (RenderCV has one position per entry)
        stacked = "\n".join(f"{t.title} ({t.year_range()})" for t in emp.titles)
        highlights = list(emp.bullets)
        if emp.intro:
            highlights = [emp.intro] + highlights
        entry: dict[str, Any] = {
            "company": emp.company,
            "position": stacked if len(emp.titles) > 1 else newest.title,
            "highlights": highlights,
        }
        if emp.location:
            entry["location"] = emp.location
        if newest.startDate:
            # Overall company span: earliest start → latest end among titles
            starts = [t.startDate for t in emp.titles if t.startDate]
            ends = [t.endDate for t in emp.titles if t.endDate]
            entry["start_date"] = _rendercv_date(min(starts) if starts else newest.startDate)
            if ends:
                entry["end_date"] = _rendercv_date(max(ends))
            else:
                entry["end_date"] = "present"
        experience_entries.append(entry)
    if experience_entries:
        sections["experience"] = experience_entries

    project_entries: list[dict[str, Any]] = []
    project_by_id = {p["_id"]: p for p in projects if p.get("_id")}
    if layout.projects:
        # Independent software engineer section as projects block
        for proj in layout.projects:
            entry: dict[str, Any] = {
                "name": proj.name,
                "highlights": proj.bullets,
            }
            source = project_by_id.get(proj.projectId) or {}
            if source.get("startDate"):
                entry["start_date"] = _rendercv_date(source["startDate"])
            if source.get("summary"):
                entry["summary"] = source["summary"]
            project_entries.append(entry)
    if project_entries:
        sections["projects"] = project_entries

    if layout.educationLines:
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

    # Preferred section order: summary → highlights → skills → experience → projects → education
    preferred_order = [
        "summary",
        "highlights",
        "skills",
        "experience",
        "projects",
        "education",
    ]
    ordered_sections: dict[str, Any] = {}
    for key in preferred_order:
        if key in sections:
            ordered_sections[key] = sections.pop(key)
    for key, value in sections.items():
        ordered_sections[key] = value

    headline = layout.professionalTitle or payload.targetRole or None
    if layout.specialtyLine and headline:
        headline = f"{headline} | {layout.specialtyLine}"
    elif layout.specialtyLine:
        headline = layout.specialtyLine

    cv: dict[str, Any] = {
        "name": layout.name,
        "location": candidate.get("location") or None,
        "email": candidate.get("email") or None,
        "sections": ordered_sections,
    }
    if headline:
        cv["headline"] = headline

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
