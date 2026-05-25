from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_user_first_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='username',
            field=models.CharField(
                blank=True,
                max_length=50,
                null=True,
                unique=True,
                verbose_name='שם משתמש',
            ),
        ),
        migrations.AddField(
            model_name='user',
            name='last_name',
            field=models.CharField(blank=True, max_length=60, verbose_name='שם משפחה'),
        ),
    ]
