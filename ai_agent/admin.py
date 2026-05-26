from django.contrib import admin, messages
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html

from .models import AIChangeRequest
from .permissions import can_use_ai_agent
from .services.workflow import (
    approve_and_create_pr,
    generate_diff_for_request,
    reject_request,
)


@admin.register(AIChangeRequest)
class AIChangeRequestAdmin(admin.ModelAdmin):
    change_form_template = 'admin/ai_agent/aichangerequest/change_form.html'
    list_display = (
        'id', 'prompt_preview', 'status', 'created_by',
        'created_at', 'pr_link',
    )
    list_filter = ('status', 'created_at')
    search_fields = ('prompt', 'branch_name', 'error_message')
    readonly_fields = (
        'status', 'result', 'error_message', 'branch_name',
        'pr_url', 'pr_number', 'files_touched', 'processing_log',
        'created_by', 'created_at', 'updated_at', 'diff_preview',
    )
    fieldsets = (
        ('בקשה', {
            'fields': ('prompt', 'status', 'created_by', 'created_at', 'updated_at'),
        }),
        ('תוצאה', {
            'fields': ('diff_preview', 'result', 'files_touched', 'processing_log', 'error_message'),
        }),
        ('Git / PR', {
            'fields': ('branch_name', 'pr_number', 'pr_url'),
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('created_by')

    def has_module_permission(self, request):
        return can_use_ai_agent(request.user)

    def has_view_permission(self, request, obj=None):
        return can_use_ai_agent(request.user)

    def has_add_permission(self, request):
        return can_use_ai_agent(request.user)

    def has_change_permission(self, request, obj=None):
        return can_use_ai_agent(request.user)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
            obj.status = AIChangeRequest.Status.DRAFT
        super().save_model(request, obj, form, change)

    def get_readonly_fields(self, request, obj=None):
        ro = list(self.readonly_fields)
        if obj is None:
            return [f for f in ro if f not in ('status', 'created_by', 'created_at', 'updated_at')]
        if obj.status not in (
            AIChangeRequest.Status.DRAFT,
            AIChangeRequest.Status.FAILED,
            AIChangeRequest.Status.CANCELLED,
        ):
            ro = ro + ['prompt']
        return ro

    @admin.display(description='בקשה')
    def prompt_preview(self, obj):
        return (obj.prompt or '')[:80]

    @admin.display(description='PR')
    def pr_link(self, obj):
        if obj.pr_url:
            return format_html('<a href="{}" target="_blank">#{}</a>', obj.pr_url, obj.pr_number or '')
        return '—'

    @admin.display(description='תצוגת diff')
    def diff_preview(self, obj):
        if not obj or not obj.result:
            return '—'
        escaped = (
            obj.result.replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
        )
        return format_html(
            '<pre style="max-height:420px;overflow:auto;background:#0d1117;color:#e6edf3;'
            'padding:12px;font-size:12px;direction:ltr;text-align:left;">{}</pre>',
            escaped,
        )

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                '<path:object_id>/generate-diff/',
                self.admin_site.admin_view(self.generate_diff_view),
                name='ai_agent_aichangerequest_generate',
            ),
            path(
                '<path:object_id>/approve-pr/',
                self.admin_site.admin_view(self.approve_pr_view),
                name='ai_agent_aichangerequest_approve',
            ),
            path(
                '<path:object_id>/reject/',
                self.admin_site.admin_view(self.reject_view),
                name='ai_agent_aichangerequest_reject',
            ),
        ]
        return custom + urls

    def generate_diff_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        if not obj:
            self.message_user(request, 'רשומה לא נמצאה', level=messages.ERROR)
            return redirect('..')
        try:
            generate_diff_for_request(obj)
            self.message_user(request, 'ה-diff נוצר – בדוק בתצוגה לפני אישור PR', level=messages.SUCCESS)
        except Exception as exc:
            self.message_user(request, f'שגיאה: {exc}', level=messages.ERROR)
        return redirect(reverse('admin:ai_agent_aichangerequest_change', args=[object_id]))

    def approve_pr_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        if not obj:
            self.message_user(request, 'רשומה לא נמצאה', level=messages.ERROR)
            return redirect('..')
        try:
            approve_and_create_pr(obj)
            self.message_user(
                request,
                f'PR נוצר: {obj.pr_url}',
                level=messages.SUCCESS,
            )
        except Exception as exc:
            self.message_user(request, f'שגיאה: {exc}', level=messages.ERROR)
        return redirect(reverse('admin:ai_agent_aichangerequest_change', args=[object_id]))

    def reject_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        if obj:
            reject_request(obj)
            self.message_user(request, 'הבקשה נדחתה', level=messages.WARNING)
        return redirect(reverse('admin:ai_agent_aichangerequest_change', args=[object_id]))

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        obj = self.get_object(request, object_id)
        if obj:
            extra_context['ai_agent_actions'] = {
                'can_generate': obj.status in (
                    AIChangeRequest.Status.DRAFT,
                    AIChangeRequest.Status.FAILED,
                    AIChangeRequest.Status.CANCELLED,
                ),
                'can_approve_pr': obj.status == AIChangeRequest.Status.DIFF_READY,
                'can_reject': obj.status in (
                    AIChangeRequest.Status.DIFF_READY,
                    AIChangeRequest.Status.DRAFT,
                ),
                'generate_url': reverse('admin:ai_agent_aichangerequest_generate', args=[object_id]),
                'approve_url': reverse('admin:ai_agent_aichangerequest_approve', args=[object_id]),
                'reject_url': reverse('admin:ai_agent_aichangerequest_reject', args=[object_id]),
            }
        return super().change_view(request, object_id, form_url, extra_context)
