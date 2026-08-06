"""OpenAI multi-stage application package orchestrator."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from ..resume.achievements import Achievement
from ..resume.legacy import build_tailored_resume_lines
from ..resume.tailor import MAX_BULLETS_BY_PAGES, TailorPayload, tailor_resume
from .consistency import ConsistencyResult, review_consistency
from .cover_letter import build_cover_letter, ensure_letter_envelope
from .evidence_ranker import EvidenceRanking, rank_evidence
from .job_analyzer import JobAnalysis, analyze_job_for_package
from .reports import (
    application_report,
    ats_checklist_markdown,
    enhanced_application_answers,
    fit_assessment_markdown,
    keyword_coverage_markdown,
    selection_changelog_markdown,
    talking_points_markdown,
    tailoring_strategy_markdown,
)
from .resume_critic import ResumeCriticResult, critique_resume

logger = logging.getLogger(__name__)


@dataclass
class PackagePipelineResult:
    payload: TailorPayload
    cover_letter: str
    analysis: JobAnalysis
    ranking: EvidenceRanking
    critic: ResumeCriticResult | None
    consistency: ConsistencyResult | None
    pipeline: str = "openai-multistage"
    stages: dict[str, Any] = field(default_factory=dict)
    # JSON dicts or markdown strings — serialized by documents.py
    artifacts: dict[str, Any] = field(default_factory=dict)
    application_report: dict[str, Any] = field(default_factory=dict)
    application_answers: str = ""


def run_openai_package_pipeline(
    *,
    candidate: dict,
    job: dict,
    match: dict,
    catalog: list[Achievement],
    skills: list[dict],
    projects: list[dict],
    work_history: list[dict],
    evidence_used: list[dict],
    pages: Literal[1, 2] = 2,
) -> PackagePipelineResult:
    """Run job analysis → rank → tailor → critic → cover → consistency."""
    stages: dict[str, Any] = {}

    analysis = analyze_job_for_package(
        job=job, match=match, candidate=candidate
    )
    stages["jobAnalyzer"] = {
        "source": analysis.source,
        "provider": analysis.provider,
    }

    max_bullets = MAX_BULLETS_BY_PAGES.get(pages, 12)
    ranking = rank_evidence(
        analysis=analysis,
        match=match,
        catalog=catalog,
        skills=skills,
        projects=projects,
        max_bullets=max_bullets,
    )
    stages["evidenceRanker"] = {
        "source": ranking.source,
        "provider": ranking.provider,
        "topIds": ranking.ordered_ids(limit=8),
    }

    bullet_cap = ranking.recommendedBulletCap or max_bullets
    payload = tailor_resume(
        candidate=candidate,
        job=job,
        match=match,
        catalog=catalog,
        skills=skills,
        pages=pages,
        analysis=analysis.to_public(),
        ranking=ranking.to_public(),
        max_bullets_override=bullet_cap,
        work_history=work_history,
        projects=projects,
    )
    stages["resumeTailor"] = {
        "usedLlm": payload.usedLlm,
        "provider": payload.provider,
        "fallbackReason": payload.fallbackReason,
        "bulletCount": len(payload.selectedAchievementIds),
        "revision": 0,
    }
    pre_revision_payload: TailorPayload | None = None

    # Critic + optional one revision
    resume_preview = "\n".join(
        build_tailored_resume_lines(
            candidate=candidate,
            skills=skills,
            work_history=work_history,
            projects=projects,
            catalog=catalog,
            payload=payload,
            job=job,
        )
    )
    critic = critique_resume(
        resume_preview=resume_preview,
        job=job,
        analysis=analysis,
        payload_report=payload.to_report(),
    )
    stages["resumeCritic"] = critic.to_public()

    selection_changelog_md: str | None = None
    if critic.needs_revision() and payload.usedLlm:
        logger.info(
            "Resume critic requested revision (mean=%.1f mustFix=%s)",
            critic.mean,
            len(critic.mustFix),
        )
        pre_revision_payload = payload
        revised = tailor_resume(
            candidate=candidate,
            job=job,
            match=match,
            catalog=catalog,
            skills=skills,
            pages=pages,
            analysis=analysis.to_public(),
            ranking=ranking.to_public(),
            max_bullets_override=bullet_cap,
            critic_feedback=critic.feedback_text(),
            work_history=work_history,
            projects=projects,
        )
        if revised.selectedAchievementIds:
            payload = revised
            stages["resumeTailor"]["revision"] = 1
            stages["resumeTailor"]["provider"] = revised.provider
            stages["resumeTailor"]["usedLlm"] = revised.usedLlm
            resume_preview = "\n".join(
                build_tailored_resume_lines(
                    candidate=candidate,
                    skills=skills,
                    work_history=work_history,
                    projects=projects,
                    catalog=catalog,
                    payload=payload,
                    job=job,
                )
            )
            selection_changelog_md = selection_changelog_markdown(
                before=pre_revision_payload,
                after=payload,
                job=job,
            )

    cover = build_cover_letter(
        candidate=candidate,
        job=job,
        match=match,
        analysis=analysis,
        payload=payload,
        catalog=catalog,
        work_history=work_history,
        projects=projects,
        evidence_used=evidence_used,
    )
    stages["coverLetter"] = {"length": len(cover)}

    consistency = review_consistency(
        resume_text=resume_preview,
        cover_letter=cover,
        analysis=analysis,
        payload=payload,
        catalog=catalog,
    )
    cover = consistency.safeCoverLetter or cover
    cover = ensure_letter_envelope(cover, candidate=candidate, job=job)
    stages["consistencyReview"] = consistency.to_public()

    pipeline_meta = {
        "pipeline": "openai-multistage",
        "stages": stages,
    }
    critic_public = critic.to_public()
    consistency_public = consistency.to_public()

    fit_md = fit_assessment_markdown(
        job=job,
        match=match,
        analysis=analysis,
        payload=payload,
        catalog=catalog,
        skills=skills,
        critic_scores=critic_public,
        resume_text=resume_preview,
        cover_text=cover,
    )
    keywords_md = keyword_coverage_markdown(
        analysis=analysis,
        resume_text=resume_preview,
        cover_text=cover,
    )
    checklist_md = ats_checklist_markdown(
        resume_text=resume_preview,
        analysis=analysis,
        cover_text=cover,
    )
    talking_md = talking_points_markdown(
        job=job,
        analysis=analysis,
        payload=payload,
        catalog=catalog,
    )
    strategy_md = tailoring_strategy_markdown(
        job=job,
        analysis=analysis,
        ranking=ranking,
        payload=payload,
        pipeline_meta=pipeline_meta,
    )
    answers = enhanced_application_answers(
        candidate=candidate,
        job=job,
        match=match,
        analysis=analysis,
        payload=payload,
        evidence_used=evidence_used,
        talking_points_md=talking_md,
    )
    report = application_report(
        job=job,
        match=match,
        analysis=analysis,
        ranking=ranking,
        payload=payload,
        critic=critic_public,
        consistency=consistency_public,
        pipeline_meta=pipeline_meta,
        evidence_ids_used=[e["_id"] for e in evidence_used if e.get("_id")],
    )

    artifacts: dict[str, Any] = {
        "job-analysis.json": analysis.to_public(),
        "evidence-ranking.json": ranking.to_public(),
        "ats-keywords.md": keywords_md,
        "ats-checklist.md": checklist_md,
        "fit-assessment.md": fit_md,
        "interview-talking-points.md": talking_md,
        "tailoring-strategy.md": strategy_md,
        "application-report.json": report,
    }
    if selection_changelog_md:
        artifacts["selection-changelog.md"] = selection_changelog_md

    return PackagePipelineResult(
        payload=payload,
        cover_letter=cover,
        analysis=analysis,
        ranking=ranking,
        critic=critic,
        consistency=consistency,
        pipeline="openai-multistage",
        stages=stages,
        artifacts=artifacts,
        application_report=report,
        application_answers=answers,
    )
