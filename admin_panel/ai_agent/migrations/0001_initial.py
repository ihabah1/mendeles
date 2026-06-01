import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AIChangeRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('prompt', models.TextField(verbose_name='בקשה בשפה טבעית')),
                ('status', models.CharField(
                    choices=[
                        ('draft', 'טיוטה'),
                        ('generating', 'מייצר diff'),
                        ('diff_ready', 'מוכן לבדיקה'),
                        ('approved', 'אושר ליצירת PR'),
                        ('pr_creating', 'יוצר PR'),
                        ('pr_created', 'PR נוצר'),
                        ('rejected', 'נדחה'),
                        ('failed', 'נכשל'),
                    ],
                    db_index=True,
                    default='draft',
                    max_length=20,
                )),
                ('result', models.TextField(blank=True, verbose_name='תוצאה / diff')),
                ('error_message', models.TextField(blank=True, verbose_name='שגיאה')),
                ('branch_name', models.CharField(blank=True, max_length=120, verbose_name='שם ענף')),
                ('pr_url', models.URLField(blank=True, verbose_name='קישור PR')),
                ('pr_number', models.PositiveIntegerField(blank=True, null=True)),
                ('files_touched', models.JSONField(blank=True, default=list)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='ai_change_requests',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='נוצר על ידי',
                )),
            ],
            options={
                'verbose_name': 'בקשת שינוי AI',
                'verbose_name_plural': 'בקשות שינוי AI',
                'ordering': ['-created_at'],
            },
        ),
    ]
