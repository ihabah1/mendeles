"""תזמור: generate diff → preview → approve → PR."""
from __future__ import annotations

import re

from django.utils import timezone

from admin_panel.ai_agent.git_tools.github_pr import GitHubPRError, create_pull_request, merge_pull_request
from admin_panel.ai_agent.git_tools.repo import GitToolError, apply_diff_and_push
from admin_panel.ai_agent.models import AIChangeRequest

from .change_history import record_site_change
from .gemini_service import GeminiServiceError, generate_diff
from .publish_scope import classify_publish_scope, scope_warning


def _branch_name(request: AIChangeRequest) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', (request.prompt or '')[:40].lower()).strip('-')
    ts = timezone.now().strftime('%Y%m%d%H%M')
    return f'ai-agent/{request.pk or "new"}-{ts}-{slug or "change"}'[:80]


def generate_diff_for_request(request: AIChangeRequest, *, resume: bool = False) -> AIChangeRequest:
    """ללא transaction.atomic – שומר לוג ל-DB בזמן אמת ל-polling."""
    if request.status == AIChangeRequest.Status.GENERATING:
        if not resume:
            raise ValueError('הבקשה כבר בעיבוד')
    elif request.status not in (
        AIChangeRequest.Status.DRAFT,
        AIChangeRequest.Status.FAILED,
        AIChangeRequest.Status.CANCELLED,
        AIChangeRequest.Status.DIFF_READY,
    ):
        raise ValueError('לא ניתן לייצר diff בסטטוס הנוכחי')
    else:
        request.clear_log()
        request.append_log('מתחיל עיבוד בקשה…')

    request.status = AIChangeRequest.Status.GENERATING
    request.error_message = ''
    request.save(update_fields=['status', 'error_message', 'updated_at'])

    def log(msg: str):
        request.append_log(msg)

    try:
        log('טוען קבצים מותרים (templates/, static/)…')
        from .image_attachments import image_paths_for_request

        imgs = image_paths_for_request(request.pk, request.reference_images)
        diff = generate_diff(
            request.prompt,
            log_callback=log,
            image_paths=imgs or None,
        )
        from .path_guard import extract_paths_from_diff

        log('מאמת מבנה diff ונתיבים…')
        paths = extract_paths_from_diff(diff)
        log(f'נמצאו {len(paths)} קבצים: {", ".join(paths[:5])}{"…" if len(paths) > 5 else ""}')

        request.result = diff
        request.files_touched = paths
        request.publish_scope = classify_publish_scope(paths)
        request.status = AIChangeRequest.Status.DIFF_READY
        request.error_message = ''
        request.append_log('הושלם – diff מוכן לבדיקה')
        warn = scope_warning(request.publish_scope, paths)
        if warn:
            request.append_log(f'שים לב: {warn}')
    except (GeminiServiceError, ValueError) as exc:
        request.status = AIChangeRequest.Status.FAILED
        request.error_message = str(exc)
        request.append_log(f'שגיאה: {exc}')
        request.save(update_fields=['status', 'error_message', 'updated_at'])
        raise

    request.save(
        update_fields=['result', 'files_touched', 'publish_scope', 'status', 'error_message', 'updated_at'],
    )
    return request


def approve_and_create_pr(request: AIChangeRequest, *, resume: bool = False) -> AIChangeRequest:
    """ללא transaction.atomic – לוג נשמר ב-DB בזמן אמת ל-polling."""
    if request.status == AIChangeRequest.Status.PR_CREATING:
        if not resume:
            raise ValueError('הבקשה כבר בתהליך יצירת PR')
    elif request.status != AIChangeRequest.Status.DIFF_READY:
        raise ValueError('יש לאשר רק בקשה עם diff מוכן לבדיקה')
    if not request.result.strip():
        raise ValueError('אין diff ליישום')

    if request.status == AIChangeRequest.Status.DIFF_READY:
        request.clear_log()
        request.append_log('מאשר בקשה…')
        request.status = AIChangeRequest.Status.APPROVED
        request.save(update_fields=['status', 'updated_at'])

    request.status = AIChangeRequest.Status.PR_CREATING
    request.error_message = ''
    request.append_log('מכין ענף Git…')
    request.save(update_fields=['status', 'error_message', 'updated_at'])

    branch = request.branch_name or _branch_name(request)
    request.branch_name = branch
    request.save(update_fields=['branch_name', 'updated_at'])

    def log(msg: str) -> None:
        request.append_log(msg)

    try:
        try:
            touched = apply_diff_and_push(
                request.pk,
                request.result,
                branch,
                log_callback=log,
            )
        except GitToolError as exc:
            msg = str(exc)
            if 'patch failed' in msg or 'does not apply' in msg:
                raise GitToolError(
                    'ה-diff לא תואם לקבצים ב-GitHub. לחץ "ייצר diff" מחדש '
                    '(המערכת קוראת עכשיו מ-origin/main).',
                ) from exc
            raise
        request.files_touched = touched
        request.publish_scope = classify_publish_scope(touched)
        log('יוצר Pull Request ב-GitHub…')

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
            'status', 'branch_name', 'pr_number', 'pr_url', 'publish_scope',
            'files_touched', 'error_message', 'updated_at',
        ],
    )
    return request


def merge_pr_for_request(request: AIChangeRequest, performed_by=None) -> AIChangeRequest:
    if request.status not in (
        AIChangeRequest.Status.PR_CREATED,
        AIChangeRequest.Status.PR_MERGED,
    ):
        raise ValueError('ניתן למזג רק אחרי יצירת PR')
    if not request.pr_number:
        raise ValueError('אין מספר PR')

    request.append_log('ממזג PR ל-main ב-GitHub…')
    try:
        sha = merge_pull_request(request.pr_number)
        request.status = AIChangeRequest.Status.PR_MERGED
        request.merged_at = timezone.now()
        request.publish_scope = classify_publish_scope(request.files_touched or [])
        request.error_message = ''
        request.append_log(f'מוזג בהצלחה ל-main (commit: {sha[:7] if sha and len(sha) > 7 else sha})')
        request.append_log('Git עודכן – Railway אמור להתחיל deploy')
        warn = scope_warning(request.publish_scope, request.files_touched or [])
        if warn:
            request.append_log(f'שים לב: {warn}')
        if performed_by:
            record_site_change(request, performed_by)
    except (GitHubPRError, ValueError) as exc:
        request.error_message = str(exc)
        request.append_log(f'שגיאה במיזוג: {exc}')
        request.save(update_fields=['error_message', 'updated_at'])
        raise

    request.save(
        update_fields=['status', 'merged_at', 'publish_scope', 'error_message', 'updated_at'],
    )
    return request


def reject_request(request: AIChangeRequest) -> AIChangeRequest:
    request.status = AIChangeRequest.Status.REJECTED
    request.save(update_fields=['status', 'updated_at'])
    return request


# ניתן לבטל ידנית כשהתהליך תקוע (השרת נפל / PR תקוע)
CANCELLABLE_STATUSES = frozenset({
    AIChangeRequest.Status.GENERATING,
    AIChangeRequest.Status.PR_CREATING,
    AIChangeRequest.Status.APPROVED,
    AIChangeRequest.Status.PR_CREATED,
})


def can_cancel_request(request: AIChangeRequest) -> bool:
    return request.status in CANCELLABLE_STATUSES


def archive_request(
    request: AIChangeRequest,
    *,
    performed_by=None,
    reason: str = '',
) -> AIChangeRequest:
    """מסיר מהרשימה בפורטל; מתועד ב-היסטוריית פעולות. לא מוחק מה-DB."""
    from admin_panel.ai_agent.services.change_history import record_ai_request_archived
    from admin_panel.ai_agent.services.job_queue import cancel_jobs_for_request

    from .pipeline import build_pipeline, can_archive_request

    if not can_archive_request(request):
        raise ValueError('הרשומה כבר הוסרה מהרשימה.')

    pipeline = build_pipeline(request)
    stages_done = [s['label'] for s in pipeline['stages'] if s.get('done')]
    stages_pending = [s['label'] for s in pipeline['stages'] if not s.get('done')]

    prev_label = request.get_status_display()
    cancel_jobs_for_request(request.pk, reason=reason or 'הוסר מהרשימה')
    note = (reason or 'הוסר מניהול שינויים').strip()
    request.append_log(f'🗑 הוסר מהרשימה (היה: {prev_label}). {note}')
    request.status = AIChangeRequest.Status.ARCHIVED
    request.error_message = ''
    request.save(update_fields=['status', 'error_message', 'updated_at'])
    record_ai_request_archived(
        request,
        performed_by,
        reason=note,
        previous_status=prev_label,
        stages_done=stages_done,
        stages_pending=stages_pending,
    )
    return request


def cancel_request(request: AIChangeRequest, *, reason: str = '') -> AIChangeRequest:
    """מבטל ג'וב תקוע – מאפס סטטוס כדי לאפשר ניסיון חוזר."""
    from admin_panel.ai_agent.services.job_queue import cancel_jobs_for_request

    if not can_cancel_request(request):
        raise ValueError(
            f'לא ניתן לבטל בסטטוס «{request.get_status_display()}». '
            'רק בזמן יצירת diff, יצירת PR, או PR פתוח.'
        )
    n = cancel_jobs_for_request(request.pk, reason=reason or 'בוטל עם הבקשה')
    if n:
        request.append_log(f'[תור] בוטלו {n} ג\'ובים בתור')

    prev = request.get_status_display()
    request.status = AIChangeRequest.Status.CANCELLED
    note = reason.strip() or 'בוטל ידנית – אפשר ללחוץ «ייצר diff» מחדש'
    request.error_message = note
    request.append_log(f'⛔ בוטל (היה: {prev}). {note}')
    if request.pr_url:
        request.append_log(
            f'PR #{request.pr_number} עדיין ב-GitHub – סגור ידנית אם לא נדרש: {request.pr_url}',
        )
    request.save(update_fields=['status', 'error_message', 'updated_at'])
    return request
