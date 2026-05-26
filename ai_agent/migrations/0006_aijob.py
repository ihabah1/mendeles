import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ai_agent', '0005_aichangerequest_cancelled_status'),
    ]

    operations = [
        migrations.CreateModel(
            name='AIJob',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('job_type', models.CharField(choices=[('generate_diff', 'ייצור diff'), ('create_pr', 'יצירת PR'), ('merge_pr', 'מיזוג ל-main')], db_index=True, max_length=20)),
                ('status', models.CharField(choices=[('pending', 'ממתין בתור'), ('running', 'רץ'), ('completed', 'הושלם'), ('failed', 'נכשל'), ('cancelled', 'בוטל')], db_index=True, default='pending', max_length=20)),
                ('attempts', models.PositiveSmallIntegerField(default=0)),
                ('max_attempts', models.PositiveSmallIntegerField(default=3)),
                ('error_message', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('change_request', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='jobs', to='ai_agent.aichangerequest', verbose_name='בקשה')),
            ],
            options={
                'verbose_name': "ג'וב AI",
                'verbose_name_plural': "תור ג'ובים AI",
                'ordering': ['created_at'],
            },
        ),
    ]
