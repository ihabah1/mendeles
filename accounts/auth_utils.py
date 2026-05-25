from accounts.models import User

MSG_USER_NOT_FOUND = 'משתמש לא קיים'
MSG_WRONG_PASSWORD = 'סיסמה שגויה'
MSG_INACTIVE = 'החשבון אינו פעיל'
MSG_MISSING = 'נא למלא אימייל וסיסמה'


def authenticate_user(email: str, password: str) -> tuple[User | None, str | None]:
    """אימות עם הודעות שגיאה מפורשות (לא קיים / סיסמה שגויה)."""
    email = (email or '').strip().lower()
    password = password or ''
    if not email or not password:
        return None, MSG_MISSING

    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        return None, MSG_USER_NOT_FOUND

    if not user.is_active:
        return None, MSG_INACTIVE

    if not user.check_password(password):
        return None, MSG_WRONG_PASSWORD

    return user, None
