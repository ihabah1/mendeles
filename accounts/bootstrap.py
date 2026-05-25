"""מנהל ברירת מחדל – נוצר/מתוקן בכל migrate/setup ואיתחול."""
from django.conf import settings

from accounts.models import User

BOOTSTRAP_ADMIN_EMAIL = 'admin@admin.com'
BOOTSTRAP_ADMIN_PASSWORD = 'admin'


def ensure_bootstrap_admin() -> tuple[User, bool]:
    """מבטיח ש-admin@admin.com / admin קיים, פעיל, עם הרשאות מנהל."""
    admin, created = User.objects.get_or_create(
        email=BOOTSTRAP_ADMIN_EMAIL,
        defaults={
            'full_name': 'מנהל מערכת',
            'phone': '0500000000',
            'role': User.Role.ADMIN,
            'is_staff': True,
            'is_superuser': True,
            'is_active': True,
        },
    )
    admin.set_password(BOOTSTRAP_ADMIN_PASSWORD)
    admin.is_staff = True
    admin.is_superuser = True
    admin.is_active = True
    admin.role = User.Role.ADMIN
    if not admin.full_name:
        admin.full_name = 'מנהל מערכת'
    admin.save()
    return admin, created
