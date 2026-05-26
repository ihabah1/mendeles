"""בקשות שינוי AI בדשבורד /manage/."""
from django.conf import settings
from django.contrib import messages
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from portal.decorators import admin_required
from portal.forms import AIChangeRequestForm

from ai_agent.models import AIChangeRequest, AIJob
from ai_agent.services.publish_scope import scope_label, scope_warning
from ai_agent.services.job_queue import (
    cancel_single_job,
    enqueue,
    infer_retry_job_type,
    queue_status_for_request,
    queue_status_global,
    request_action_fields,
    retry_request_step,
)
from ai_agent.services.pipeline import build_pipeline, pipeline_to_json
from ai_agent.services.workflow import (
    archive_request,
    cancel_request,
    can_cancel_request,
    merge_pr_for_request,
    reject_request,
)


def _can_retry_request(obj: AIChangeRequest) -> bool:
    if not infer_retry_job_type(obj):
        return False
    if obj.status in (
        AIChangeRequest.Status.FAILED,
        AIChangeRequest.Status.CANCELLED,
    ):
        return True
    if obj.status in (
        AIChangeRequest.Status.GENERATING,
        AIChangeRequest.Status.PR_CREATING,
        AIChangeRequest.Status.APPROVED,
    ):
        return not AIJob.objects.filter(
            change_request=obj,
            status__in=(AIJob.Status.PENDING, AIJob.Status.RUNNING),
        ).exists()
    return False


def _ai_available() -> bool:
    return getattr(settings, 'AI_AGENT_ENABLED', False)


def _require_ai_enabled():
    if not _ai_available():
        raise Http404


def _wants_json(request) -> bool:
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return True
    accept = request.headers.get('Accept', '')
    return 'application/json' in accept


def _status_payload(obj: AIChangeRequest) -> dict:
    logs = obj.processing_log or []
    last = logs[-1] if logs else {}
    return {
        'id': obj.pk,
        'status': obj.status,
        'status_label': obj.get_status_display(),
        'logs': logs,
        'last_log': last.get('msg', ''),
        'last_log_ts': last.get('ts', ''),
        'updated_at': obj.updated_at.isoformat() if obj.updated_at else '',
        'error': obj.error_message or '',
        'failed': obj.status == AIChangeRequest.Status.FAILED,
        'in_progress': obj.status in (
            AIChangeRequest.Status.GENERATING,
            AIChangeRequest.Status.PR_CREATING,
            AIChangeRequest.Status.APPROVED,
        ),
        'generating': obj.status == AIChangeRequest.Status.GENERATING,
        'pr_creating': obj.status == AIChangeRequest.Status.PR_CREATING,
        'done': obj.status in (
            AIChangeRequest.Status.DIFF_READY,
            AIChangeRequest.Status.FAILED,
            AIChangeRequest.Status.PR_CREATED,
            AIChangeRequest.Status.CANCELLED,
        ),
        'cancelled': obj.status == AIChangeRequest.Status.CANCELLED,
        'can_cancel': can_cancel_request(obj),
        'ok': obj.status == AIChangeRequest.Status.DIFF_READY,
        'pr_url': obj.pr_url or '',
        'pr_number': obj.pr_number,
        'can_merge': (
            obj.status == AIChangeRequest.Status.PR_CREATED and bool(obj.pr_number)
        ),
        'merged': obj.status == AIChangeRequest.Status.PR_MERGED,
        'merge_url': reverse('portal:ai_request_merge', kwargs={'pk': obj.pk})
        if obj.pr_number
        else '',
        'publish_scope': obj.publish_scope or '',
        'publish_scope_label': scope_label(obj.publish_scope or ''),
        'scope_warning': scope_warning(obj.publish_scope or '', obj.files_touched or []) or '',
        'queue': queue_status_for_request(obj.pk),
        'can_retry': _can_retry_request(obj),
        'actions': request_action_fields(obj),
        'approve_url': reverse('portal:ai_request_approve', kwargs={'pk': obj.pk}),
        'reject_url': reverse('portal:ai_request_reject', kwargs={'pk': obj.pk}),
        'cancel_url': reverse('portal:ai_request_cancel', kwargs={'pk': obj.pk}),
        'pipeline': pipeline_to_json(
            obj,
            list(AIJob.objects.filter(change_request=obj).order_by('-created_at')[:12]),
        ),
    }


@admin_required
def ai_jobs_list(request):
    _require_ai_enabled()
    g = queue_status_global()
    return render(request, 'portal/ai_jobs.html', {
        'jobs': g['jobs'],
        'queue_summary': g,
        'queue_status_url': reverse('portal:ai_queue_status'),
    })


@admin_required
@require_GET
def ai_queue_status(request):
    _require_ai_enabled()
    return JsonResponse(queue_status_global())


@admin_required
def ai_requests_list(request):
    _require_ai_enabled()
    reqs = (
        AIChangeRequest.objects.exclude(status=AIChangeRequest.Status.ARCHIVED)
        .select_related('created_by')
        .order_by('-created_at')[:50]
    )
    request_rows = [
        {
            'req': r,
            'act': request_action_fields(r),
            'pipeline': build_pipeline(r),
        }
        for r in reqs
    ]
    return render(request, 'portal/ai_requests.html', {
        'request_rows': request_rows,
    })


@admin_required
def ai_request_create(request):
    _require_ai_enabled()
    form = AIChangeRequestForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        obj = AIChangeRequest.objects.create(
            prompt=form.cleaned_data['prompt'].strip(),
            status=AIChangeRequest.Status.DRAFT,
            created_by=request.user,
        )
        uploads = request.FILES.getlist('images')
        if uploads:
            from ai_agent.services.image_attachments import save_uploaded_images

            saved = save_uploaded_images(obj.pk, uploads)
            if saved:
                obj.reference_images = saved
                obj.save(update_fields=['reference_images'])
                messages.info(request, f'צורפו {len(saved)} תמונות לבקשה')
        messages.success(request, 'הבקשה נשמרה – לחץ "ייצר diff" ליצירת השינוי')
        return redirect('portal:ai_request_detail', pk=obj.pk)
    preview = ''
    try:
        from ai_agent.services.site_index import format_index_summary

        preview = format_index_summary(settings.BASE_DIR)
    except Exception:
        preview = ''
    return render(
        request,
        'portal/ai_request_form.html',
        {'form': form, 'site_index_preview': preview},
    )


@admin_required
def ai_request_detail(request, pk):
    _require_ai_enabled()
    obj = AIChangeRequest.objects.filter(pk=pk).first()
    if not obj:
        messages.warning(
            request,
            f'בקשה #{pk} לא נמצאה. ייתכן שהמסד אופס (SQLite ב-Railway). צור בקשה חדשה.',
        )
        return redirect('portal:ai_requests')
    if obj.status == AIChangeRequest.Status.ARCHIVED:
        messages.info(request, f'בקשה #{pk} הוסרה מהרשימה. פרטים ב«היסטוריית פעולות».')
        return redirect('portal:ai_requests')
    is_generating = obj.status == AIChangeRequest.Status.GENERATING
    is_pr_creating = obj.status == AIChangeRequest.Status.PR_CREATING
    is_in_progress = obj.status in (
        AIChangeRequest.Status.GENERATING,
        AIChangeRequest.Status.PR_CREATING,
        AIChangeRequest.Status.APPROVED,
    )
    return render(request, 'portal/ai_request_detail.html', {
        'req': obj,
        'can_generate': obj.status in (
            AIChangeRequest.Status.DRAFT,
            AIChangeRequest.Status.FAILED,
            AIChangeRequest.Status.CANCELLED,
        ) and not is_generating and not is_pr_creating,
        'can_cancel': can_cancel_request(obj),
        'cancel_url': reverse('portal:ai_request_cancel', kwargs={'pk': pk}),
        'can_approve': obj.status == AIChangeRequest.Status.DIFF_READY and bool(obj.result),
        'can_reject': obj.status in (
            AIChangeRequest.Status.DIFF_READY,
            AIChangeRequest.Status.DRAFT,
        ) and not is_generating and not is_pr_creating,
        'is_generating': is_generating,
        'is_pr_creating': is_pr_creating,
        'is_in_progress': is_in_progress,
        'status_url': reverse('portal:ai_request_status', kwargs={'pk': pk}),
        'generate_url': reverse('portal:ai_request_generate', kwargs={'pk': pk}),
        'approve_url': reverse('portal:ai_request_approve', kwargs={'pk': pk}),
        'merge_url': reverse('portal:ai_request_merge', kwargs={'pk': pk}),
        'can_merge': (
            obj.status == AIChangeRequest.Status.PR_CREATED and bool(obj.pr_number)
        ),
        'is_merged': obj.status == AIChangeRequest.Status.PR_MERGED,
        'scope_warning': scope_warning(obj.publish_scope or '', obj.files_touched or []),
        'publish_scope_label': scope_label(obj.publish_scope or ''),
        'can_retry': _can_retry_request(obj),
        'retry_url': reverse('portal:ai_request_retry', kwargs={'pk': pk}),
        'queue': queue_status_for_request(pk),
        'request_actions': request_action_fields(obj),
        'pipeline': build_pipeline(obj),
    })


@admin_required
@require_GET
def ai_request_status(request, pk):
    _require_ai_enabled()
    obj = get_object_or_404(AIChangeRequest, pk=pk)
    return JsonResponse(_status_payload(obj))


@admin_required
@require_POST
def ai_request_generate(request, pk):
    _require_ai_enabled()
    obj = get_object_or_404(AIChangeRequest, pk=pk)
    ajax = _wants_json(request)

    if obj.status == AIChangeRequest.Status.GENERATING:
        if ajax:
            return JsonResponse({**_status_payload(obj), 'message': 'כבר בתהליך'})
        messages.warning(request, 'הבקשה כבר בעיבוד')
        return redirect('portal:ai_request_detail', pk=pk)

    if ajax:
        try:
            enqueue(pk, AIJob.JobType.GENERATE_DIFF)
            obj.refresh_from_db()
            return JsonResponse({
                **_status_payload(obj),
                'message': 'נוסף לתור – ג\'וב אחד בכל פעם, הלוג מתעדכן כל 3 שניות',
            })
        except ValueError as exc:
            return JsonResponse({**_status_payload(obj), 'ok': False, 'error': str(exc)}, status=400)

    messages.info(request, 'השתמש בכפתור «ייצר diff» בדף הבקשה (תור רקע)')
    return redirect('portal:ai_request_detail', pk=pk)


@admin_required
@require_POST
def ai_request_approve(request, pk):
    _require_ai_enabled()
    obj = get_object_or_404(AIChangeRequest, pk=pk)
    ajax = _wants_json(request)

    if obj.status == AIChangeRequest.Status.PR_CREATING:
        if ajax:
            return JsonResponse({**_status_payload(obj), 'message': 'כבר בתור/בריצה – עקוב אחרי הלוג'})
        return redirect('portal:ai_request_detail', pk=pk)

    if obj.status != AIChangeRequest.Status.DIFF_READY:
        if ajax:
            return JsonResponse(
                {**_status_payload(obj), 'ok': False, 'error': 'אין diff מוכן לאישור'},
                status=400,
            )
        messages.error(request, 'אין diff מוכן לאישור')
        return redirect('portal:ai_request_detail', pk=pk)

    if ajax:
        try:
            enqueue(pk, AIJob.JobType.CREATE_PR)
            obj.refresh_from_db()
            return JsonResponse({
                **_status_payload(obj),
                'message': 'יצירת PR נוספה לתור – לא מקביל לג\'ובים אחרים',
            })
        except ValueError as exc:
            return JsonResponse({**_status_payload(obj), 'ok': False, 'error': str(exc)}, status=400)

    messages.info(request, 'השתמש בכפתור «אשר ויצור PR» בדף הבקשה')
    return redirect('portal:ai_request_detail', pk=pk)


@admin_required
@require_POST
def ai_request_merge(request, pk):
    _require_ai_enabled()
    obj = get_object_or_404(AIChangeRequest, pk=pk)
    ajax = _wants_json(request)

    if obj.status == AIChangeRequest.Status.PR_MERGED:
        if ajax:
            return JsonResponse({
                **_status_payload(obj),
                'git_updated': True,
                'message': 'Git כבר עודכן (PR מוזג קודם)',
            })
        messages.success(request, 'ה-PR כבר מוזג ל-main')
        return redirect('portal:ai_request_detail', pk=pk)

    if obj.status != AIChangeRequest.Status.PR_CREATED or not obj.pr_number:
        if ajax:
            return JsonResponse({**_status_payload(obj), 'ok': False}, status=400)
        messages.error(request, 'אין PR למיזוג')
        return redirect('portal:ai_request_detail', pk=pk)

    if ajax:
        try:
            enqueue(pk, AIJob.JobType.MERGE_PR, performed_by=request.user)
            obj.refresh_from_db()
            return JsonResponse({
                **_status_payload(obj),
                'message': 'מיזוג נוסף לתור',
            })
        except ValueError as exc:
            return JsonResponse({**_status_payload(obj), 'ok': False, 'error': str(exc)}, status=400)

    try:
        merge_pr_for_request(obj, performed_by=request.user)
        obj.refresh_from_db()
        messages.success(request, 'Git עודכן – PR מוזג')
    except Exception as exc:
        obj.refresh_from_db()
        messages.error(request, str(exc))

    return redirect('portal:ai_request_detail', pk=pk)


@admin_required
@require_POST
def ai_request_retry(request, pk):
    _require_ai_enabled()
    obj = get_object_or_404(AIChangeRequest, pk=pk)
    ajax = _wants_json(request)

    try:
        retry_request_step(pk, performed_by=request.user)
        obj.refresh_from_db()
        if ajax:
            return JsonResponse({
                **_status_payload(obj),
                'message': 'השלב הוכנס מחדש לתור',
            })
        messages.success(request, 'השלב הוכנס מחדש לתור')
    except ValueError as exc:
        if ajax:
            return JsonResponse({**_status_payload(obj), 'ok': False, 'error': str(exc)}, status=400)
        messages.error(request, str(exc))

    return redirect('portal:ai_request_detail', pk=pk)


@admin_required
@require_GET
def ai_request_image(request, pk, filename):
    _require_ai_enabled()
    obj = get_object_or_404(AIChangeRequest, pk=pk)
    if filename not in (obj.reference_images or []):
        raise Http404
    from ai_agent.services.image_attachments import _mime_for_path, request_images_dir

    path = request_images_dir(pk) / filename
    if not path.is_file():
        raise Http404
    return FileResponse(path.open('rb'), content_type=_mime_for_path(path))


@admin_required
@require_POST
def ai_request_cancel(request, pk):
    _require_ai_enabled()
    obj = get_object_or_404(AIChangeRequest, pk=pk)
    ajax = _wants_json(request)
    reason = (request.POST.get('reason') or '').strip()

    try:
        cancel_request(obj, reason=reason)
        obj.refresh_from_db()
        if ajax:
            return JsonResponse({
                **_status_payload(obj),
                'message': 'הג\'וב בוטל – אפשר לנסות שוב',
                'redirect': reverse('portal:ai_request_detail', kwargs={'pk': pk}),
            })
        messages.success(request, 'הג\'וב בוטל. אפשר ללחוץ «ייצר diff» מחדש.')
    except ValueError as exc:
        if ajax:
            return JsonResponse({**_status_payload(obj), 'ok': False, 'error': str(exc)}, status=400)
        messages.error(request, str(exc))

    return redirect('portal:ai_request_detail', pk=pk)


@admin_required
@require_POST
def ai_request_archive(request, pk):
    _require_ai_enabled()
    obj = get_object_or_404(AIChangeRequest, pk=pk)
    ajax = _wants_json(request)
    reason = (request.POST.get('reason') or 'הוסר מניהול שינויים').strip()

    try:
        archive_request(obj, performed_by=request.user, reason=reason)
        if ajax:
            return JsonResponse({
                'ok': True,
                'message': 'הרשומה הוסרה מהרשימה ותועדה בהיסטוריית פעולות',
                'redirect': reverse('portal:ai_requests'),
            })
        messages.success(
            request,
            'הרשומה הוסרה מ«ניהול שינויים» ותועדה ב«היסטוריית פעולות».',
        )
    except ValueError as exc:
        if ajax:
            return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
        messages.error(request, str(exc))

    return redirect('portal:ai_requests')


@admin_required
@require_POST
def ai_request_reject(request, pk):
    _require_ai_enabled()
    obj = get_object_or_404(AIChangeRequest, pk=pk)
    ajax = _wants_json(request)
    reject_request(obj)
    obj.refresh_from_db()
    if ajax:
        return JsonResponse({
            **_status_payload(obj),
            'message': 'הבקשה נדחתה',
        })
    messages.warning(request, 'הבקשה נדחתה')
    return redirect('portal:ai_request_detail', pk=pk)


@admin_required
@require_POST
def ai_job_cancel(request, job_id):
    _require_ai_enabled()
    ajax = _wants_json(request)
    reason = (request.POST.get('reason') or 'בוטל מהטבלה').strip()
    job = get_object_or_404(AIJob, pk=job_id)
    if not cancel_single_job(job_id, reason=reason):
        if ajax:
            return JsonResponse({'ok': False, 'error': 'לא ניתן לבטל ג\'וב זה'}, status=400)
        messages.error(request, 'לא ניתן לבטל ג\'וב זה')
        return redirect('portal:ai_request_detail', pk=job.change_request_id)
    req = AIChangeRequest.objects.get(pk=job.change_request_id)
    if ajax:
        return JsonResponse({
            **_status_payload(req),
            'message': 'הג\'וב בוטל',
        })
    messages.success(request, 'הג\'וב בוטל')
    return redirect('portal:ai_request_detail', pk=job.change_request_id)
