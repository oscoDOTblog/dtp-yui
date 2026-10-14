"""Structured DOCX from validated TailorPayload (not PDF→Word)."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.shared import Pt

from .achievements import Achievement
from .layout import build_resume_layout
from .tailor import TailorPayload


def render_tailored_docx(
    path: Path,
    *,
    candidate: dict,
    skills: list[dict],
    work_history: list[dict],
    projects: list[dict],
    catalog: list[Achievement],
    payload: TailorPayload,
    job: dict | None = None,
) -> None:
    layout = build_resume_layout(
        candidate=candidate,
        skills=skills,
        work_history=work_history,
        projects=projects,
        catalog=catalog,
        payload=payload,
    )

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10)

    doc.add_heading(layout.name, level=0)
    if layout.professionalTitle:
        p = doc.add_paragraph()
        run = p.add_run(layout.professionalTitle)
        run.bold = True
    if layout.specialtyLine:
        doc.add_paragraph(layout.specialtyLine)
    if layout.contactLine:
        doc.add_paragraph(layout.contactLine)

    if layout.summary:
        doc.add_heading("SUMMARY", level=1)
        doc.add_paragraph(layout.summary)

    if layout.highlights:
        doc.add_heading("SELECTED HIGHLIGHTS", level=1)
        for h in layout.highlights:
            doc.add_paragraph(h, style="List Bullet")

    if layout.coreExpertise:
        doc.add_heading("CORE EXPERTISE", level=1)
        doc.add_paragraph(layout.coreExpertise)

    if layout.employers:
        doc.add_heading("EXPERIENCE", level=1)
        for emp in layout.employers:
            header = emp.company
            if emp.location:
                header = f"{emp.company} — {emp.location}"
            p = doc.add_paragraph()
            run = p.add_run(header)
            run.bold = True
            for t in emp.titles:
                doc.add_paragraph(f"{t.title} ({t.year_range()})")
            if emp.intro:
                doc.add_paragraph(emp.intro)
            for bullet in emp.bullets:
                doc.add_paragraph(bullet, style="List Bullet")

    if layout.projects:
        heading = (layout.independentLabel or "INDEPENDENT SOFTWARE ENGINEER").strip()
        doc.add_heading(heading, level=1)
        period_loc = layout.independentPeriod
        if layout.independentLocation:
            period_loc = f"{layout.independentPeriod} | {layout.independentLocation}"
        if period_loc:
            doc.add_paragraph(period_loc)
        for proj in layout.projects:
            p = doc.add_paragraph()
            run = p.add_run(proj.name)
            run.bold = True
            for bullet in proj.bullets:
                doc.add_paragraph(bullet, style="List Bullet")

    if layout.technologyLines:
        doc.add_heading("TECHNOLOGIES", level=1)
        for line in layout.technologyLines:
            doc.add_paragraph(line)

    if layout.educationLines:
        doc.add_heading("EDUCATION", level=1)
        for line in layout.educationLines:
            doc.add_paragraph(line)

    doc.save(str(path))
