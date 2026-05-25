from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _ensure_bootstrap_admin(sender, **kwargs):
    if sender.name != 'accounts':
        return
    from accounts.bootstrap import ensure_bootstrap_admin

    ensure_bootstrap_admin()


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'
    verbose_name = 'חשבונות'

    def ready(self):
        post_migrate.connect(_ensure_bootstrap_admin, sender=self)
