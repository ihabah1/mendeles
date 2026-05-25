from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ai_agent', '0003_aichangerequest_merged_at_publish_scope'),
    ]

    operations = [
        migrations.AddField(
            model_name='aichangerequest',
            name='reference_images',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='שמות קבצים בתיקיית data/ai_requests/<id>/',
                verbose_name='תמונות מצורפות',
            ),
        ),
    ]
