"""תזמור: generate diff → preview → approve → PR."""
from __future__ import annotations

import re

from django.db import transaction
from django.utils import timezone

from ai_agent.git_tools.github_pr import GitHubPRError, create_pull_request
from ai_agent.git_tools.repo import GitToolError, apply_diff_and_push
from ai_agent.models import AIChangeRequest

from .gemini_service import GeminiServiceError, generate_diff


def _branch_name(request: AIChangeRequest) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', (request.prompt or '')[:40].lower()).strip('-')
    ts = timezone.now().strftime('%Y%m%d%H%M')
    return f'ai-agent/{request.pk or "new"}-{ts}-{slug or "change"}'[:80]


def generate_diff_for_request(request: AIChangeRequest) -> AIChangeRequest:
    """ללא transaction.atomic – שומר לוג ל-DB בזמן אמת ל-polling."""
    if request.status not in (
        AIChangeRequest.Status.DRAFT,
        AIChangeRequest.Status.FAILED,
        AIChangeRequest.Status.DIFF_READY,
    ):
        raise ValueError('לא ניתן לייצר diff בסטטוס הנוכחי')

    request.clear_log()
    request.append_log('מתחיל עיבוד בקשה…')
    request.status = AIChangeRequest.Status.GENERATING
    request.error_message = ''
    request.save(update_fields=['status', 'error_message', 'updated_at'])

    def log(msg: str):
        request.append_log(msg)

    try:
        log('טוען קבצים מותרים (templates/, static/)…')
        diff = generate_diff(request.prompt, log_callback=log)
        from .path_guard import extract_paths_from_diff

        log('מאמת מבנה diff ונתיבים…')
        paths = extract_paths_from_diff(diff)
        log(f'נמצאו {len(paths)} קבצים: {", ".join(paths[:5])}{"…" if len(paths) > 5 else ""}')

        request.result = diff
        request.files_touched = paths
        request.status = AIChangeRequest.Status.DIFF_READY
        request.error_message = ''
        request.append_log('הושלם – diff מוכן לבדיקה')
    except (GeminiServiceError, ValueError) as exc:
        request.status = AIChangeRequest.Status.FAILED
        request.error_message = str(exc)
        request.append_log(f'שגיאה: {exc}')
        request.save(update_fields=['status', 'error_message', 'updated_at'])
        raise

    request.save(update_fields=['result', 'files_touched', 'status', 'error_message', 'updated_at'])
    return request


@transaction.atomic
def approve_and_create_pr(request: AIChangeRequest) -> AIChangeRequest:
    if request.status != AIChangeRequest.Status.DIFF_READY:
        raise ValueError('יש לאשר רק בקשה עם diff מוכן לבדיקה')
    if not request.result.strip():
        raise ValueError('אין diff ליישום')

    request.clear_log()
    request.append_log('מאשר בקשה…')
    request.status = AIChangeRequest.Status.APPROVED
    request.save(update_fields=['status', 'updated_at'])

    request.status = AIChangeRequest.Status.PR_CREATING
    request.append_log('מכין ענף Git…')
    request.save(update_fields=['status', 'updated_at'])

    branch = request.branch_name or _branch_name(request)
    request.branch_name = branch

    try:
        request.append_log(f'מיישם diff על ענף {branch}…')
        touched = apply_diff_and_push(request.pk, request.result, branch)
        request.files_touched = touched
        request.append_log('דוחף ל-GitHub…')

        pr_number, pr_url = create_pull_request(
            branch_name=branch,
            title=f'AI: {(request.prompt or "")[:72]}',
            body=(
                f'בקשת שינוי AI #{request.pk}\n\n'
                f'**Prompt:**\n{request.prompt}\n\n'
                f'**קבצים:** {", ".join(touched)}\n\n'
                'נוצר אוטומטית – יש לבדוק לפני merge.'
            ),
        )
        request.pr_number = pr_number
        request.pr_url = pr_url
        request.status = AIChangeRequest.Status.PR_CREATED
        request.error_message = ''
        request.append_log(f'PR #{pr_number} נוצר בהצלחה')
    except (GitToolError, GitHubPRError, ValueError) as exc:
        request.status = AIChangeRequest.Status.FAILED
        request.error_message = str(exc)
        request.append_log(f'שגיאה: {exc}')
        request.save(update_fields=['status', 'error_message', 'branch_name', 'updated_at'])
        raise

    request.save(
        update_fields=[
            'status', 'branch_name', 'pr_number', 'pr_url',
            'files_touched', 'error_message', 'updated_at',
        ],
    )
    return request


def reject_request(request: AIChangeRequest) -> AIChangeRequest:
    request.status = AIChangeRequest.Status.REJECTED
    request.save(update_fields=['status', 'updated_at'])
    return request
