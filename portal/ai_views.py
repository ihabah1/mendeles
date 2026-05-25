"""בקשות שינוי AI בדשבורד /manage/."""
from django.conf import settings
from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from portal.decorators import admin_required
from portal.forms import AIChangeRequestForm

from ai_agent.models import AIChangeRequest
from ai_agent.services.workflow import (
    approve_and_create_pr,
    generate_diff_for_request,
    reject_request,
)


def _ai_available() -> bool:
    return getattr(settings, 'AI_AGENT_ENABLED', False)


def _require_ai_enabled():
    if not _ai_available():
        raise Http404


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
    return render(request, 'portal/ai_request_form.html', {'form': form})


@admin_required
def ai_request_detail(request, pk):
    _require_ai_enabled()
    obj = get_object_or_404(AIChangeRequest, pk=pk)
    return render(request, 'portal/ai_request_detail.html', {
        'req': obj,
        'can_generate': obj.status in (
            AIChangeRequest.Status.DRAFT,
            AIChangeRequest.Status.FAILED,
        ),
        'can_approve': obj.status == AIChangeRequest.Status.DIFF_READY and bool(obj.result),
        'can_reject': obj.status in (
            AIChangeRequest.Status.DIFF_READY,
            AIChangeRequest.Status.DRAFT,
        ),
    })


@admin_required
@require_POST
def ai_request_generate(request, pk):
    _require_ai_enabled()
    obj = get_object_or_404(AIChangeRequest, pk=pk)
    try:
        generate_diff_for_request(obj)
        messages.success(request, 'ה-diff נוצר – בדוק לפני אישור PR')
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect('portal:ai_request_detail', pk=pk)


@admin_required
@require_POST
def ai_request_approve(request, pk):
    _require_ai_enabled()
    obj = get_object_or_404(AIChangeRequest, pk=pk)
    try:
        approve_and_create_pr(obj)
        messages.success(request, f'PR נוצר: {obj.pr_url}')
    except Exception as exc:
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
