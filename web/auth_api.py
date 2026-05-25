import json
import re

from django.conf import settings
from django.contrib.auth import login, logout
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from accounts.auth_utils import authenticate_user
from accounts.bootstrap import BOOTSTRAP_ADMIN_EMAIL, ensure_bootstrap_admin
from accounts.models import User

EMAIL_RE = re.compile(r'^[^@]+@[^@]+\.[^@]+$')
USERNAME_RE = re.compile(r'^[a-zA-Z0-9_\u0590-\u05FF]{3,50}$')
PHONE_RE = re.compile(r'^[\d\s\-+()]{7,20}$')


def _json_body(request):
    try:
        return json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return {}


def _is_portal_admin(user) -> bool:
    return bool(
        user
        and user.is_authenticated
        and user.email.lower() == settings.ADMIN_EMAIL.lower()
    )


def _user_payload(user):
    return {
        'id': user.id,
        'email': user.email,
        'username': user.username or '',
        'first_name': user.first_name or '',
        'last_name': user.last_name or '',
        'full_name': user.full_name or '',
        'phone': user.phone or '',
        'display_name': user.display_name,
        'is_admin': _is_portal_admin(user),
    }


def _normalize_username(raw: str) -> str:
    return (raw or '').strip().lower()


@ensure_csrf_cookie
@require_http_methods(['GET'])
def csrf(request):
    token = get_token(request)
    return JsonResponse({'ok': True, 'csrfToken': token})


@require_http_methods(['GET'])
def me(request):
    if not request.user.is_authenticated:
        return JsonResponse({'user': None})
    return JsonResponse({'user': _user_payload(request.user)})


@require_http_methods(['POST'])
def register_view(request):
    data = _json_body(request)
    username = _normalize_username(data.get('username') or '')
    first_name = (data.get('first_name') or data.get('firstName') or '').strip()
    last_name = (data.get('last_name') or data.get('lastName') or '').strip()
    password = data.get('password') or ''
    password2 = data.get('password_confirm') or data.get('password2') or ''
    phone = (data.get('phone') or '').strip()[:20]
    email = (data.get('email') or '').strip().lower()

    if not USERNAME_RE.match(username):
        return JsonResponse(
            {'error': 'שם משתמש: 3–50 תווים (אותיות, מספרים, _)'},
            status=400,
        )
    if len(first_name) < 2:
        return JsonResponse({'error': 'נא להזין שם פרטי (לפחות 2 תווים)'}, status=400)
    if len(last_name) < 2:
        return JsonResponse({'error': 'נא להזין שם משפחה (לפחות 2 תווים)'}, status=400)
    if len(password) < 6:
        return JsonResponse({'error': 'סיסמה לפחות 6 תווים'}, status=400)
    if password != password2:
        return JsonResponse({'error': 'הסיסמאות אינן תואמות'}, status=400)
    if phone and not PHONE_RE.match(phone):
        return JsonResponse({'error': 'מספר טלפון לא תקין'}, status=400)
    if User.objects.filter(username__iexact=username).exists():
        return JsonResponse({'error': 'שם המשתמש תפוס'}, status=400)

    if not email or not EMAIL_RE.match(email):
        email = f'{username}@users.mandeles.co.il'
    if User.objects.filter(email=email).exists():
        return JsonResponse({'error': 'כתובת אימייל כבר רשומה'}, status=400)

    user = User.objects.create_user(
        email=email,
        password=password,
        role=User.Role.CUSTOMER,
        username=username,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
    )
    user.sync_full_name()
    user.save(update_fields=['full_name'])

    login(request, user)
    return JsonResponse({'user': _user_payload(user)}, status=201)


@require_http_methods(['GET', 'POST', 'PATCH'])
def profile_view(request):
    """קריאה ועדכון פרטי משתמש מחובר (Django session)."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'נדרשת התחברות'}, status=401)

    user = request.user
    if request.method == 'GET':
        return JsonResponse({'user': _user_payload(user)})

    data = _json_body(request)
    first_name = (data.get('first_name') or '').strip()
    last_name = (data.get('last_name') or '').strip()
    phone = (data.get('phone') or '').strip()[:20]
    username = _normalize_username(data.get('username') or '') or (user.username or '')

    if first_name and len(first_name) < 2:
        return JsonResponse({'error': 'שם פרטי קצר מדי'}, status=400)
    if last_name and len(last_name) < 2:
        return JsonResponse({'error': 'שם משפחה קצר מדי'}, status=400)
    if username and not USERNAME_RE.match(username):
        return JsonResponse({'error': 'שם משתמש לא תקין'}, status=400)
    if username and User.objects.filter(username__iexact=username).exclude(pk=user.pk).exists():
        return JsonResponse({'error': 'שם המשתמש תפוס'}, status=400)
    if phone and not PHONE_RE.match(phone):
        return JsonResponse({'error': 'מספר טלפון לא תקין'}, status=400)

    if first_name:
        user.first_name = first_name
    if last_name:
        user.last_name = last_name
    if username:
        user.username = username
    user.phone = phone
    user.sync_full_name()
    user.save(update_fields=['first_name', 'last_name', 'username', 'full_name', 'phone'])

    return JsonResponse({'ok': True, 'user': _user_payload(user)})


@require_http_methods(['POST'])
def login_view(request):
    data = _json_body(request)
    identifier = (data.get('email') or data.get('username') or '').strip()
    password = data.get('password') or ''

    if identifier.lower() == BOOTSTRAP_ADMIN_EMAIL.lower():
        ensure_bootstrap_admin()

    user, err = authenticate_user(identifier, password)
    if err:
        return JsonResponse({'error': err}, status=401)

    login(request, user)
    return JsonResponse({'user': _user_payload(user)})


@require_http_methods(['POST'])
def logout_view(request):
    logout(request)
    return JsonResponse({'ok': True})
