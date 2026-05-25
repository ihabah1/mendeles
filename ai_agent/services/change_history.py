"""תיעוד שינויים בהיסטוריית הפעולות של הפורטל."""
from __future__ import annotations

from django.contrib.auth import get_user_model

from ai_agent.models import AIChangeRequest

from .publish_scope import classify_publish_scope, scope_label

User = get_user_model()


def record_site_change(ai_request: AIChangeRequest, performed_by) -> None:
    from portal.models import ActionLog

    files = list(ai_request.files_touched or [])
    scope = ai_request.publish_scope or classify_publish_scope(files)
    lines = [
        f'בקשת AI #{ai_request.pk}',
        f'סטטוס: {ai_request.get_status_display()}',
        f'טווח: {scope_label(scope)}',
        f'בקשה: {(ai_request.prompt or "")[:500]}',
    ]
    if files:
        lines.append(f'קבצים: {", ".join(files)}')
    if ai_request.branch_name:
        lines.append(f'ענף: {ai_request.branch_name}')
    if ai_request.pr_url:
        lines.append(f'PR: {ai_request.pr_url}')
    if ai_request.merged_at:
        lines.append(f'מוזג: {ai_request.merged_at.strftime("%Y-%m-%d %H:%M")}')

    ActionLog.objects.create(
        performed_by=performed_by if getattr(performed_by, 'pk', None) else None,
        event='שינוי AI באתר',
        details='\n'.join(lines),
    )
