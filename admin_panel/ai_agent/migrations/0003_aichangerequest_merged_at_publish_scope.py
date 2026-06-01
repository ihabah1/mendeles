from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ai_agent', '0002_aichangerequest_processing_log'),
    ]

    operations = [
        migrations.AddField(
            model_name='aichangerequest',
            name='merged_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='מוזג ל-main'),
        ),
        migrations.AddField(
            model_name='aichangerequest',
            name='publish_scope',
            field=models.CharField(
                blank=True,
                choices=[
                    ('live', 'אתר ראשי (React)'),
                    ('manage', 'דשבורד ניהול בלבד'),
                    ('mixed', 'אתר + ניהול'),
                    ('unknown', 'לא ידוע'),
                ],
                max_length=20,
                verbose_name='היכן השינוי נראה',
            ),
        ),
    ]
