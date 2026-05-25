from django.conf import settings
from django.db import models


class AIChangeRequest(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'טיוטה'
        GENERATING = 'generating', 'מייצר diff'
        DIFF_READY = 'diff_ready', 'מוכן לבדיקה'
        APPROVED = 'approved', 'אושר ליצירת PR'
        PR_CREATING = 'pr_creating', 'יוצר PR'
        PR_CREATED = 'pr_created', 'PR נוצר'
        PR_MERGED = 'pr_merged', 'מוזג ל-main'
        REJECTED = 'rejected', 'נדחה'
        FAILED = 'failed', 'נכשל'

    prompt = models.TextField('בקשה בשפה טבעית')
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    result = models.TextField('תוצאה / diff', blank=True)
    error_message = models.TextField('שגיאה', blank=True)
    branch_name = models.CharField('שם ענף', max_length=120, blank=True)
    pr_url = models.URLField('קישור PR', blank=True)
    pr_number = models.PositiveIntegerField(null=True, blank=True)
    merged_at = models.DateTimeField('מוזג ל-main', null=True, blank=True)
    publish_scope = models.CharField(
        'היכן השינוי נראה',
        max_length=20,
        blank=True,
        choices=[
            ('live', 'אתר ראשי (Django)'),
            ('manage', 'דשבורד ניהול בלבד'),
            ('mixed', 'אתר + ניהול'),
            ('unknown', 'לא ידוע'),
        ],
    )
    files_touched = models.JSONField(default=list, blank=True)
    processing_log = models.JSONField('לוג עיבוד', default=list, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ai_change_requests',
        verbose_name='נוצר על ידי',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'בקשת שינוי AI'
        verbose_name_plural = 'בקשות שינוי AI'
        ordering = ['-created_at']

    def __str__(self):
        preview = (self.prompt or '')[:60]
        return f'#{self.pk} {preview} ({self.get_status_display()})'

    def clear_log(self):
        self.processing_log = []
        self.save(update_fields=['processing_log', 'updated_at'])

    def append_log(self, message: str):
        from django.utils import timezone

        logs = list(self.processing_log or [])
        logs.append({
            'ts': timezone.localtime().strftime('%H:%M:%S'),
            'msg': message,
        })
        self.processing_log = logs
        self.save(update_fields=['processing_log', 'updated_at'])
