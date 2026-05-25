"""בקשות שינוי AI בדשבורד /manage/."""
from django.conf import settings
from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from portal.decorators import admin_required
from portal.forms import AIChangeRequestForm

from ai_agent.models import AIChangeRequest
from ai_agent.services.publish_scope import scope_label, scope_warning
from ai_agent.services.workflow import (
    approve_and_create_pr,
    generate_diff_for_request,
    merge_pr_for_request,
    reject_request,
)


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
    return {
        'id': obj.pk,
        'status': obj.status,
        'status_label': obj.get_status_display(),
        'logs': obj.processing_log or [],
        'error': obj.error_message or '',
        'generating': obj.status == AIChangeRequest.Status.GENERATING,
        'pr_creating': obj.status == AIChangeRequest.Status.PR_CREATING,
        'done': obj.status in (
            AIChangeRequest.Status.DIFF_READY,
            AIChangeRequest.Status.FAILED,
            AIChangeRequest.Status.PR_CREATED,
        ),
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
    }


@admin_required
def ai_requests_list(request):
    _require_ai_enabled()
    reqs = AIChangeRequest.objects.select_related('created_by').order_by('-created_at')[:50]
    return render(request, 'portal/ai_requests.html', {'requests': reqs})


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
    is_generating = obj.status == AIChangeRequest.Status.GENERATING
    is_pr_creating = obj.status == AIChangeRequest.Status.PR_CREATING
    return render(request, 'portal/ai_request_detail.html', {
        'req': obj,
        'can_generate': obj.status in (
            AIChangeRequest.Status.DRAFT,
            AIChangeRequest.Status.FAILED,
        ) and not is_generating and not is_pr_creating,
        'can_approve': obj.status == AIChangeRequest.Status.DIFF_READY and bool(obj.result),
        'can_reject': obj.status in (
            AIChangeRequest.Status.DIFF_READY,
            AIChangeRequest.Status.DRAFT,
        ) and not is_generating and not is_pr_creating,
        'is_generating': is_generating,
        'is_pr_creating': is_pr_creating,
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

    try:
        generate_diff_for_request(obj)
        obj.refresh_from_db()
        if ajax:
            return JsonResponse({
                **_status_payload(obj),
                'redirect': reverse('portal:ai_request_detail', kwargs={'pk': pk}),
            })
        messages.success(request, 'ה-diff נוצר – בדוק לפני אישור PR')
    except Exception as exc:
        obj.refresh_from_db()
        if ajax:
            return JsonResponse({**_status_payload(obj), 'ok': False}, status=400)
        messages.error(request, str(exc))

    return redirect('portal:ai_request_detail', pk=pk)


@admin_required
@require_POST
def ai_request_approve(request, pk):
    _require_ai_enabled()
    obj = get_object_or_404(AIChangeRequest, pk=pk)
    ajax = _wants_json(request)

    if obj.status == AIChangeRequest.Status.PR_CREATING:
        if ajax:
            return JsonResponse({**_status_payload(obj), 'message': 'כבר יוצר PR'})
        return redirect('portal:ai_request_detail', pk=pk)

    try:
        approve_and_create_pr(obj)
        obj.refresh_from_db()
        if ajax:
            return JsonResponse(_status_payload(obj))
        messages.success(request, f'PR נוצר: {obj.pr_url}')
        return redirect('portal:ai_request_detail', pk=pk)
    except Exception as exc:
        obj.refresh_from_db()
        if ajax:
            return JsonResponse({**_status_payload(obj), 'ok': False}, status=400)
        messages.error(request, str(exc))

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

    try:
        merge_pr_for_request(obj, performed_by=request.user)
        obj.refresh_from_db()
        msg = 'Git עודכן בהצלחה – main מוזג, Railway יתחיל deploy'
        warn = scope_warning(obj.publish_scope or '', obj.files_touched or [])
        if warn:
            msg = f'{msg}. {warn}'
        if ajax:
            return JsonResponse({
                **_status_payload(obj),
                'git_updated': True,
                'message': msg,
            })
        messages.success(request, msg)
    except Exception as exc:
        obj.refresh_from_db()
        if ajax:
            return JsonResponse({**_status_payload(obj), 'ok': False, 'error': str(exc)}, status=400)
        messages.error(request, str(exc))

    return redirect('portal:ai_request_detail', pk=pk)


@admin_required
@require_POST
def ai_request_reject(request, pk):
    _require_ai_enabled()
    obj = get_object_or_404(AIChangeRequest, pk=pk)
    reject_request(obj)
    messages.warning(request, 'הבקשה נדחתה')
    return redirect('portal:ai_request_detail', pk=pk)
