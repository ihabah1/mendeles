from django.conf import settings


def can_use_ai_agent(user) -> bool:
    """רק superuser או מנהל מוגדר (ADMIN_EMAIL)."""
    if not getattr(settings, 'AI_AGENT_ENABLED', False):
        return False
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    email = getattr(user, 'email', '') or ''
    admin_email = getattr(settings, 'ADMIN_EMAIL', 'admin@admin.com')
    return email.lower() == admin_email.lower() and user.is_staff
