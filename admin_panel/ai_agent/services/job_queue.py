"""תור ג'ובים AI – הרצה סדרתית (לא מקביל) עם ניסיונות חוזרים."""
from __future__ import annotations

import logging
import threading
import time
from datetime import timedelta

from django.db import close_old_connections, transaction
from django.utils import timezone

from admin_panel.ai_agent.models import AIChangeRequest, AIJob
from admin_panel.ai_agent.services.workflow import (
    approve_and_create_pr,
    generate_diff_for_request,
    merge_pr_for_request,
)

logger = logging.getLogger(__name__)

_WORKER_LOCK = threading.Lock()
_WORKER_STARTED = False
_POLL_SECONDS = 2
_STALE_RUNNING_MINUTES = 12
_ADVISORY_LOCK_ID = 83429001

_EXECUTORS = {
    AIJob.JobType.GENERATE_DIFF: generate_diff_for_request,
    AIJob.JobType.CREATE_PR: approve_and_create_pr,
    AIJob.JobType.MERGE_PR: merge_pr_for_request,
}

# אוטומציה: שלב שהושלם מפעיל אוטומטית את השלב הבא (diff → PR → מיזוג ל-Git)
_NEXT_STAGE = {
    AIJob.JobType.GENERATE_DIFF: AIJob.JobType.CREATE_PR,
    AIJob.JobType.CREATE_PR: AIJob.JobType.MERGE_PR,
}


def _aijob_table_exists() -> bool:
    """False בזמן migrate לפני יצירת הטבלה – לא לגעת ב-DB ב-ready."""
    from django.db import connection

    try:
        if connection.vendor == 'postgresql':
            with connection.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = %s
                    """,
                    [AIJob._meta.db_table],
                )
                return cur.fetchone() is not None
        return AIJob._meta.db_table in connection.introspection.table_names()
    except Exception:
        return False


def ensure_queue_worker() -> None:
    """מפעיל thread יחיד שמעבד את התור (פעם אחת לתהליך)."""
    global _WORKER_STARTED
    if not _aijob_table_exists():
        return
    with _WORKER_LOCK:
        if _WORKER_STARTED:
            return
        _WORKER_STARTED = True
        recover_stale_jobs()
        thread = threading.Thread(target=_worker_loop, name='ai-job-queue', daemon=True)
        thread.start()
        logger.info('AI job queue worker started')


def start_worker_when_db_ready() -> None:
    """ממתין לטבלת התור (אחרי migrate) – לא שואל DB ב-AppConfig.ready ישירות."""
    close_old_connections()
    for _ in range(90):
        if _aijob_table_exists():
            ensure_queue_worker()
            return
        time.sleep(2)
    logger.warning('AI job queue: ai_agent_aijob table not found after wait')


def recover_stale_jobs() -> int:
    """מחזיר ג'ובים שנתקעו ב-running אחרי קריסת worker."""
    if not _aijob_table_exists():
        return 0
    cutoff = timezone.now() - timedelta(minutes=_STALE_RUNNING_MINUTES)
    stale = list(
        AIJob.objects.filter(status=AIJob.Status.RUNNING, started_at__lt=cutoff),
    )
    for job in stale:
        req = job.change_request
        req.append_log(
            f'[תור] ג\'וב #{job.pk} נראה תקוע – מוחזר לתור (ניסיון {job.attempts}/{job.max_attempts})',
        )
        job.status = AIJob.Status.PENDING
        job.started_at = None
        job.error_message = 'התהליך נקטע – ממתין להרצה מחדש'
        job.save(update_fields=['status', 'started_at', 'error_message'])
    return len(stale)


def _queue_position(job: AIJob) -> int:
    return (
        AIJob.objects.filter(
            status=AIJob.Status.PENDING,
            created_at__lte=job.created_at,
        ).count()
    )


def enqueue(
    change_request_id: int,
    job_type: str,
    *,
    max_attempts: int = 3,
    performed_by=None,
) -> AIJob:
    """מוסיף משימה לתור. לא יוצר כפילות לאותו סוג שכבר ממתין/רץ."""
    if not _aijob_table_exists():
        raise RuntimeError('טבלת תור הג\'ובים לא קיימת – הרץ migrate (ai_agent 0006)')
    ensure_queue_worker()

    with transaction.atomic():
        existing = (
            AIJob.objects.select_for_update()
            .filter(
                change_request_id=change_request_id,
                job_type=job_type,
                status__in=(AIJob.Status.PENDING, AIJob.Status.RUNNING),
            )
            .first()
        )
        if existing:
            return existing

        req = AIChangeRequest.objects.select_for_update().get(pk=change_request_id)
        job = AIJob.objects.create(
            change_request=req,
            job_type=job_type,
            status=AIJob.Status.PENDING,
            max_attempts=max_attempts,
        )
        if performed_by is not None:
            job._performed_by = performed_by  # noqa: SLF001 – מועבר ל-merge בלבד

        ahead = AIJob.objects.filter(status=AIJob.Status.PENDING).count()
        running = AIJob.objects.filter(status=AIJob.Status.RUNNING).exists()
        pos = _queue_position(job)
        req.append_log(
            f'[תור] נוסף: {job.get_job_type_display()} · מיקום {pos}'
            + (f' · {ahead} ממתינים' if ahead > 1 else '')
            + (' · ג\'וב אחר רץ כעת' if running else ''),
        )

    return job


def request_action_fields(req: AIChangeRequest | None) -> dict:
    """דגלים ו-URLs לפעולות בשורת טבלה (לפי סטטוס הבקשה)."""
    from django.urls import reverse

    from admin_panel.ai_agent.services.workflow import can_cancel_request

    if not req:
        return {
            'can_approve': False,
            'can_reject': False,
            'can_cancel_request': False,
            'can_merge': False,
            'can_generate': False,
            'approve_url': '',
            'reject_url': '',
            'cancel_url': '',
            'merge_url': '',
            'generate_url': '',
        }
    pk = req.pk
    is_generating = req.status == AIChangeRequest.Status.GENERATING
    is_pr_creating = req.status == AIChangeRequest.Status.PR_CREATING
    return {
        'can_approve': (
            req.status == AIChangeRequest.Status.DIFF_READY and bool((req.result or '').strip())
        ),
        'can_reject': req.status in (
            AIChangeRequest.Status.DIFF_READY,
            AIChangeRequest.Status.DRAFT,
        ) and not is_generating and not is_pr_creating,
        'can_cancel_request': can_cancel_request(req),
        'can_merge': (
            req.status == AIChangeRequest.Status.PR_CREATED and bool(req.pr_number)
        ),
        'can_generate': req.status in (
            AIChangeRequest.Status.DRAFT,
            AIChangeRequest.Status.FAILED,
            AIChangeRequest.Status.CANCELLED,
        ) and not is_generating and not is_pr_creating,
        'approve_url': reverse('portal:ai_request_approve', kwargs={'pk': pk}),
        'reject_url': reverse('portal:ai_request_reject', kwargs={'pk': pk}),
        'cancel_url': reverse('portal:ai_request_cancel', kwargs={'pk': pk}),
        'merge_url': reverse('portal:ai_request_merge', kwargs={'pk': pk}),
        'generate_url': reverse('portal:ai_request_generate', kwargs={'pk': pk}),
    }


def cancel_single_job(job_id: int, *, reason: str = '') -> bool:
    """מבטל ג'וב בודד בתור (pending/running)."""
    job = (
        AIJob.objects.filter(pk=job_id)
        .select_related('change_request')
        .first()
    )
    if not job or job.status not in (AIJob.Status.PENDING, AIJob.Status.RUNNING):
        return False
    note = (reason or 'בוטל מהטבלה')[:500]
    now = timezone.now()
    job.status = AIJob.Status.CANCELLED
    job.finished_at = now
    job.error_message = note
    job.save(update_fields=['status', 'finished_at', 'error_message', 'updated_at'])

    req = job.change_request
    req.append_log(f'[תור] ג\'וב #{job.pk} בוטל: {job.get_job_type_display()}')
    req.save(update_fields=['updated_at'])

    if AIJob.objects.filter(
        change_request_id=req.pk,
        status__in=(AIJob.Status.PENDING, AIJob.Status.RUNNING),
    ).exists():
        return True

    if req.status in (
        AIChangeRequest.Status.GENERATING,
        AIChangeRequest.Status.PR_CREATING,
        AIChangeRequest.Status.APPROVED,
    ):
        from admin_panel.ai_agent.services.workflow import cancel_request

        cancel_request(req, reason=note)
    return True


def cancel_jobs_for_request(change_request_id: int, *, reason: str = '') -> int:
    now = timezone.now()
    note = reason or 'בוטל'
    updated = AIJob.objects.filter(
        change_request_id=change_request_id,
        status__in=(AIJob.Status.PENDING, AIJob.Status.RUNNING),
    ).update(
        status=AIJob.Status.CANCELLED,
        finished_at=now,
        error_message=note[:500],
    )
    return updated


def infer_retry_job_type(req: AIChangeRequest) -> str | None:
    """איזה שלב להריץ מחדש לפי סטטוס הבקשה."""
    if req.status in (
        AIChangeRequest.Status.DRAFT,
        AIChangeRequest.Status.FAILED,
        AIChangeRequest.Status.CANCELLED,
    ):
        return AIJob.JobType.GENERATE_DIFF
    if req.status == AIChangeRequest.Status.GENERATING:
        return AIJob.JobType.GENERATE_DIFF
    if req.status in (
        AIChangeRequest.Status.DIFF_READY,
        AIChangeRequest.Status.APPROVED,
        AIChangeRequest.Status.PR_CREATING,
    ):
        if req.result.strip():
            return AIJob.JobType.CREATE_PR
        return AIJob.JobType.GENERATE_DIFF
    if req.status == AIChangeRequest.Status.PR_CREATED and req.pr_number:
        return AIJob.JobType.MERGE_PR
    return None


def retry_request_step(change_request_id: int, *, performed_by=None) -> AIJob:
    """מבטל ג'ובים פעילים ומוסיף מחדש את השלב המתאים."""
    req = AIChangeRequest.objects.get(pk=change_request_id)
    job_type = infer_retry_job_type(req)
    if not job_type:
        raise ValueError(f'לא ניתן להמשיך בסטטוס «{req.get_status_display()}»')

    cancel_jobs_for_request(change_request_id, reason='הוחלף בניסיון חוזר')
    req.append_log(f'[תור] מפעיל מחדש: {dict(AIJob.JobType.choices).get(job_type, job_type)}')
    req.error_message = ''
    req.save(update_fields=['error_message', 'updated_at'])

    return enqueue(change_request_id, job_type, performed_by=performed_by)


def list_recent_jobs(limit: int = 80) -> list[dict]:
    jobs = (
        AIJob.objects.select_related('change_request')
        .order_by('-created_at')[:limit]
    )
    return [_job_dict(job) for job in jobs]


def queue_status_global() -> dict:
    running = AIJob.objects.filter(status=AIJob.Status.RUNNING).select_related('change_request').first()
    return {
        'pending_global': AIJob.objects.filter(status=AIJob.Status.PENDING).count(),
        'running_global': bool(running),
        'running_job': _job_dict(running) if running else None,
        'jobs': list_recent_jobs(60),
    }


def queue_status_for_request(change_request_id: int) -> dict:
    jobs = list(
        AIJob.objects.filter(change_request_id=change_request_id)
        .select_related('change_request')
        .order_by('-created_at')[:8],
    )
    pending_global = AIJob.objects.filter(status=AIJob.Status.PENDING).count()
    running = AIJob.objects.filter(status=AIJob.Status.RUNNING).select_related('change_request').first()
    active_for_req = next((j for j in jobs if j.status == AIJob.Status.RUNNING), None)
    pending_for_req = [j for j in jobs if j.status == AIJob.Status.PENDING]

    return {
        'pending_global': pending_global,
        'running_global': bool(running),
        'running_job': _job_dict(running) if running else None,
        'active_job': _job_dict(active_for_req) if active_for_req else None,
        'pending_count': len(pending_for_req),
        'jobs': [_job_dict(j) for j in jobs],
    }


def _job_dict(job: AIJob | None) -> dict | None:
    if not job:
        return None
    req = job.change_request
    created_local = timezone.localtime(job.created_at) if job.created_at else None
    actions = request_action_fields(req)
    can_cancel_job = job.status in (AIJob.Status.PENDING, AIJob.Status.RUNNING)
    from django.urls import reverse

    cancel_job_url = reverse('portal:ai_job_cancel', kwargs={'job_id': job.pk})
    return {
        'id': job.pk,
        'request_id': job.change_request_id,
        'type': job.job_type,
        'type_label': job.get_job_type_display(),
        'status': job.status,
        'status_label': job.get_status_display(),
        'attempts': job.attempts,
        'max_attempts': job.max_attempts,
        'error': job.error_message or '',
        'created_at': job.created_at.isoformat() if job.created_at else '',
        'created_at_display': created_local.strftime('%d/%m/%Y %H:%M') if created_local else '—',
        'started_at': job.started_at.isoformat() if job.started_at else '',
        'request_prompt': (req.prompt or '').strip() if req else '',
        'request_status': req.status if req else '',
        'request_status_label': req.get_status_display() if req else '',
        'can_cancel_job': can_cancel_job,
        'cancel_job_url': cancel_job_url,
        **actions,
    }


def auto_chain_enabled() -> bool:
    from django.conf import settings

    return bool(getattr(settings, 'AI_AGENT_AUTO_CHAIN', True))


def _maybe_chain_next(job: AIJob) -> None:
    """מפעיל אוטומטית את השלב הבא לאחר שהשלב הנוכחי הושלם בהצלחה."""
    if not auto_chain_enabled():
        return
    next_type = _NEXT_STAGE.get(job.job_type)
    if not next_type:
        return
    try:
        req = AIChangeRequest.objects.get(pk=job.change_request_id)
    except AIChangeRequest.DoesNotExist:
        return

    if req.status in (
        AIChangeRequest.Status.CANCELLED,
        AIChangeRequest.Status.REJECTED,
        AIChangeRequest.Status.ARCHIVED,
        AIChangeRequest.Status.FAILED,
    ):
        return

    if next_type == AIJob.JobType.CREATE_PR:
        if req.status != AIChangeRequest.Status.DIFF_READY or not (req.result or '').strip():
            return
    elif next_type == AIJob.JobType.MERGE_PR:
        if req.status != AIChangeRequest.Status.PR_CREATED or not req.pr_number:
            return

    performed_by = req.created_by if next_type == AIJob.JobType.MERGE_PR else None
    try:
        enqueue(req.pk, next_type, performed_by=performed_by)
        label = dict(AIJob.JobType.choices).get(next_type, next_type)
        req.append_log(f'[אוטומציה] שלב הושלם → ממשיך אוטומטית: {label}')
    except Exception as exc:
        logger.warning('auto-chain enqueue failed for req %s: %s', req.pk, exc)


def _worker_loop() -> None:
    while True:
        try:
            processed = _process_one_job()
            if not processed:
                time.sleep(_POLL_SECONDS)
        except Exception:
            logger.exception('AI queue worker loop error')
            time.sleep(_POLL_SECONDS)


def _try_acquire_global_lock() -> bool:
    """נעילה בין processes (gunicorn workers) – רק worker אחד מריץ ג'וב בכל מערכת."""
    from django.conf import settings
    from django.db import connection

    engine = settings.DATABASES.get('default', {}).get('ENGINE', '')
    if 'postgresql' not in engine:
        return True
    with connection.cursor() as cur:
        cur.execute('SELECT pg_try_advisory_lock(%s)', [_ADVISORY_LOCK_ID])
        row = cur.fetchone()
    return bool(row and row[0])


def _release_global_lock() -> None:
    from django.conf import settings
    from django.db import connection

    engine = settings.DATABASES.get('default', {}).get('ENGINE', '')
    if 'postgresql' not in engine:
        return
    with connection.cursor() as cur:
        cur.execute('SELECT pg_advisory_unlock(%s)', [_ADVISORY_LOCK_ID])


def _process_one_job() -> bool:
    close_old_connections()
    recover_stale_jobs()

    if not _try_acquire_global_lock():
        return False

    try:
        return _process_one_job_locked()
    finally:
        _release_global_lock()


def _process_one_job_locked() -> bool:
    with transaction.atomic():
        if AIJob.objects.filter(status=AIJob.Status.RUNNING).exists():
            return False

        job = (
            AIJob.objects.select_for_update()
            .filter(status=AIJob.Status.PENDING)
            .order_by('created_at')
            .first()
        )
        if not job:
            return False

        job.status = AIJob.Status.RUNNING
        job.started_at = timezone.now()
        job.attempts += 1
        job.error_message = ''
        job.save(update_fields=['status', 'started_at', 'attempts', 'error_message'])

    req = job.change_request
    req.append_log(
        f'[תור] מתחיל ג\'וב #{job.pk}: {job.get_job_type_display()} '
        f'(ניסיון {job.attempts}/{job.max_attempts})',
    )

    try:
        _execute_job(job)
        job.status = AIJob.Status.COMPLETED
        job.error_message = ''
        req.append_log(f'[תור] ג\'וב #{job.pk} הושלם בהצלחה')
    except Exception as exc:
        logger.exception('AI job #%s failed', job.pk)
        err = str(exc)[:500]
        job.error_message = err
        req.error_message = err
        req.append_log(f'[תור] שגיאה בג\'וב #{job.pk}: {err}')

        if job.attempts < job.max_attempts:
            job.status = AIJob.Status.PENDING
            job.started_at = None
            req.append_log(
                f'[תור] חוזר לתור בעוד {_POLL_SECONDS} שניות '
                f'(ניסיון {job.attempts + 1}/{job.max_attempts})',
            )
        else:
            job.status = AIJob.Status.FAILED
            if req.status in (
                AIChangeRequest.Status.GENERATING,
                AIChangeRequest.Status.PR_CREATING,
                AIChangeRequest.Status.APPROVED,
            ):
                req.status = AIChangeRequest.Status.FAILED
            req.save(update_fields=['status', 'error_message', 'updated_at'])
    finally:
        job.finished_at = timezone.now()
        job.save(update_fields=['status', 'error_message', 'finished_at'])
        close_old_connections()

    if job.status == AIJob.Status.COMPLETED:
        _maybe_chain_next(job)

    return True


def _execute_job(job: AIJob) -> None:
    close_old_connections()
    req = AIChangeRequest.objects.get(pk=job.change_request_id)
    fn = _EXECUTORS.get(job.job_type)
    if not fn:
        raise ValueError(f'סוג ג\'וב לא ידוע: {job.job_type}')

    if job.job_type == AIJob.JobType.MERGE_PR:
        performed_by = getattr(job, '_performed_by', None)
        merge_pr_for_request(req, performed_by=performed_by)
    else:
        fn(req, resume=True)
