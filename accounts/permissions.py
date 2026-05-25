from django.conf import settings


def is_portal_admin(user) -> bool:
    return bool(
        user
        and getattr(user, 'is_authenticated', False)
        and user.email.lower() == settings.ADMIN_EMAIL.lower()
    )
