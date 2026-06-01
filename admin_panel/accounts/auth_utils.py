from admin_panel.accounts.models import User

MSG_USER_NOT_FOUND = 'משתמש לא קיים'
MSG_WRONG_PASSWORD = 'סיסמה שגויה'
MSG_INACTIVE = 'החשבון אינו פעיל'
MSG_MISSING = 'נא למלא שם משתמש/אימייל וסיסמה'


def authenticate_user(identifier: str, password: str) -> tuple[User | None, str | None]:
    """אימות לפי אימייל או שם משתמש."""
    identifier = (identifier or '').strip()
    password = password or ''
    if not identifier or not password:
        return None, MSG_MISSING

    user = None
    if '@' in identifier:
        try:
            user = User.objects.get(email=identifier.lower())
        except User.DoesNotExist:
            pass
    if user is None:
        user = User.objects.filter(username__iexact=identifier).first()
    if user is None:
        return None, MSG_USER_NOT_FOUND

    if not user.is_active:
        return None, MSG_INACTIVE

    if not user.check_password(password):
        return None, MSG_WRONG_PASSWORD

    return user, None
