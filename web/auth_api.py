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
        'first_name': user.first_name or '',
        'full_name': user.full_name or '',
        'phone': user.phone or '',
        'display_name': user.display_name,
        'is_admin': _is_portal_admin(user),
    }


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
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    first_name = (data.get('first_name') or data.get('firstName') or '').strip()

    if len(first_name) < 2:
        return JsonResponse({'error': 'נא להזין שם פרטי (לפחות 2 תווים)'}, status=400)
    if not EMAIL_RE.match(email):
        return JsonResponse({'error': 'אימייל לא תקין'}, status=400)
    if len(password) < 6:
        return JsonResponse({'error': 'סיסמה לפחות 6 תווים'}, status=400)
    if User.objects.filter(email=email).exists():
        return JsonResponse({'error': 'משתמש כבר קיים'}, status=400)

    user = User.objects.create_user(
        email=email,
        password=password,
        role=User.Role.CUSTOMER,
        first_name=first_name,
        full_name=first_name,
    )
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
    phone = (data.get('phone') or '').strip()[:20]
    full_name = (data.get('full_name') or '').strip()[:120]

    if first_name and len(first_name) < 2:
        return JsonResponse({'error': 'שם פרטי קצר מדי'}, status=400)

    if first_name:
        user.first_name = first_name
        if not full_name:
            user.full_name = first_name
    if full_name:
        user.full_name = full_name
    user.phone = phone
    user.save(update_fields=['first_name', 'full_name', 'phone'])

    return JsonResponse({'ok': True, 'user': _user_payload(user)})


@require_http_methods(['POST'])
def login_view(request):
    data = _json_body(request)
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if email == BOOTSTRAP_ADMIN_EMAIL.lower():
        ensure_bootstrap_admin()

    user, err = authenticate_user(email, password)
    if err:
        return JsonResponse({'error': err}, status=401)

    login(request, user)
    return JsonResponse({'user': _user_payload(user)})


@require_http_methods(['POST'])
def logout_view(request):
    logout(request)
    return JsonResponse({'ok': True})
