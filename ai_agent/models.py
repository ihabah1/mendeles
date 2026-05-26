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
        CANCELLED = 'cancelled', 'בוטל'
        ARCHIVED = 'archived', 'הוסר מהרשימה'

    prompt = models.TextField('בקשה בשפה טבעית')
    reference_images = models.JSONField(
        'תמונות מצורפות',
        default=list,
        blank=True,
        help_text='שמות קבצים בתיקיית data/ai_requests/<id>/',
    )
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


class AIJob(models.Model):
    """משימה בתור – רצה ברצף (לא במקביל)."""

    class JobType(models.TextChoices):
        GENERATE_DIFF = 'generate_diff', 'ייצור diff'
        CREATE_PR = 'create_pr', 'יצירת PR'
        MERGE_PR = 'merge_pr', 'מיזוג ל-main'

    class Status(models.TextChoices):
        PENDING = 'pending', 'ממתין בתור'
        RUNNING = 'running', 'רץ'
        COMPLETED = 'completed', 'הושלם'
        FAILED = 'failed', 'נכשל'
        CANCELLED = 'cancelled', 'בוטל'

    change_request = models.ForeignKey(
        AIChangeRequest,
        on_delete=models.CASCADE,
        related_name='jobs',
        verbose_name='בקשה',
    )
    job_type = models.CharField(max_length=20, choices=JobType.choices, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'ג\'וב AI'
        verbose_name_plural = 'תור ג\'ובים AI'
        ordering = ['created_at']

    def __str__(self):
        return f'#{self.pk} {self.get_job_type_display()} ({self.get_status_display()})'
