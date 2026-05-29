from django.db import models


class LegacyServiceState(models.Model):
    """מצב הפעלה/כיבוי ידני לכל שירות Flask (נשמר במסד – שורד פריסה מחדש)."""

    service_key = models.CharField('מזהה שירות', max_length=32, unique=True)
    enabled = models.BooleanField('מופעל', default=True)
    note = models.CharField('הערה', max_length=200, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'מצב שירות Flask'
        verbose_name_plural = 'מצבי שירותי Flask'

    def __str__(self) -> str:
        return f'{self.service_key}: {"enabled" if self.enabled else "disabled"}'
