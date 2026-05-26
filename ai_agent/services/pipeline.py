"""שלבי תהליך שינוי AI – מצב לכל רשומת בקשה (לא לג'ובים)."""
from __future__ import annotations

from django.urls import reverse

from ai_agent.models import AIChangeRequest, AIJob
from ai_agent.services.workflow import can_cancel_request


def _job_completed(jobs: list[AIJob], job_type: str) -> bool:
    return any(
        j.job_type == job_type and j.status == AIJob.Status.COMPLETED
        for j in jobs
    )


def _job_active(jobs: list[AIJob], job_type: str) -> bool:
    return any(
        j.job_type == job_type
        and j.status in (AIJob.Status.PENDING, AIJob.Status.RUNNING)
        for j in jobs
    )


def build_pipeline(
    req: AIChangeRequest,
    jobs: list[AIJob] | None = None,
) -> dict:
    """
    שלושה שלבים ברשומת הבקשה:
    1. ייצור diff
    2. יצירת PR
    3. מיזוג / Push ל-Git
    """
    if jobs is None:
        jobs = list(req.jobs.all())

    pk = req.pk
    result_ok = bool((req.result or '').strip())
    terminal_bad = req.status in (
        AIChangeRequest.Status.REJECTED,
        AIChangeRequest.Status.FAILED,
    )

    # --- שלב 1: ייצור diff ---
    s1_done = (
        result_ok
        or req.status
        in (
            AIChangeRequest.Status.DIFF_READY,
            AIChangeRequest.Status.APPROVED,
            AIChangeRequest.Status.PR_CREATING,
            AIChangeRequest.Status.PR_CREATED,
            AIChangeRequest.Status.PR_MERGED,
        )
        or _job_completed(jobs, AIJob.JobType.GENERATE_DIFF)
    )
    s1_running = (
        req.status == AIChangeRequest.Status.GENERATING
        or _job_active(jobs, AIJob.JobType.GENERATE_DIFF)
    )
    s1_can_run = (
        not terminal_bad
        and not s1_done
        and not s1_running
        and req.status
        in (
            AIChangeRequest.Status.DRAFT,
            AIChangeRequest.Status.FAILED,
            AIChangeRequest.Status.CANCELLED,
        )
    )

    # --- שלב 2: יצירת PR ---
    s2_done = (
        bool(req.pr_number)
        or req.status
        in (
            AIChangeRequest.Status.PR_CREATED,
            AIChangeRequest.Status.PR_MERGED,
        )
        or _job_completed(jobs, AIJob.JobType.CREATE_PR)
    )
    s2_running = (
        req.status
        in (
            AIChangeRequest.Status.PR_CREATING,
            AIChangeRequest.Status.APPROVED,
        )
        or _job_active(jobs, AIJob.JobType.CREATE_PR)
    )
    s2_can_run = (
        not terminal_bad
        and s1_done
        and not s2_done
        and not s2_running
        and req.status == AIChangeRequest.Status.DIFF_READY
        and result_ok
    )

    # --- שלב 3: מיזוג / Push ---
    s3_done = (
        req.status == AIChangeRequest.Status.PR_MERGED
        or bool(req.merged_at)
        or _job_completed(jobs, AIJob.JobType.MERGE_PR)
    )
    s3_running = _job_active(jobs, AIJob.JobType.MERGE_PR)
    s3_can_run = (
        not terminal_bad
        and s2_done
        and not s3_done
        and not s3_running
        and req.status == AIChangeRequest.Status.PR_CREATED
        and bool(req.pr_number)
    )

    stages = [
        {
            'id': 'generate_diff',
            'label': 'ייצור diff',
            'short': 'Diff',
            'done': s1_done,
            'running': s1_running,
            'can_run': s1_can_run,
            'run_url': reverse('portal:ai_request_generate', kwargs={'pk': pk}),
            'run_label': 'הרץ',
        },
        {
            'id': 'create_pr',
            'label': 'יצירת PR',
            'short': 'PR',
            'done': s2_done,
            'running': s2_running,
            'can_run': s2_can_run,
            'run_url': reverse('portal:ai_request_approve', kwargs={'pk': pk}),
            'run_label': 'הרץ',
        },
        {
            'id': 'merge_git',
            'label': 'מיזוג / Push ל-Git',
            'short': 'Git',
            'done': s3_done,
            'running': s3_running,
            'can_run': s3_can_run,
            'run_url': reverse('portal:ai_request_merge', kwargs={'pk': pk}),
            'run_label': 'הרץ',
        },
    ]

    return {
        'stages': stages,
        'all_done': s1_done and s2_done and s3_done,
        'can_reject': req.status in (
            AIChangeRequest.Status.DIFF_READY,
            AIChangeRequest.Status.DRAFT,
        ) and not s1_running and not s2_running,
        'can_cancel': can_cancel_request(req),
        'reject_url': reverse('portal:ai_request_reject', kwargs={'pk': pk}),
        'cancel_url': reverse('portal:ai_request_cancel', kwargs={'pk': pk}),
        'status_url': reverse('portal:ai_request_status', kwargs={'pk': pk}),
        'detail_url': reverse('portal:ai_request_detail', kwargs={'pk': pk}),
    }


def pipeline_to_json(req: AIChangeRequest, jobs: list[AIJob] | None = None) -> dict:
    """לשימוש ב-API / polling."""
    if jobs is None:
        jobs = list(req.jobs.order_by('-created_at')[:12])
    return build_pipeline(req, jobs)
