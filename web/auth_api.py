import json
import re

from django.conf import settings
from django.contrib.auth import login, logout
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from accounts.auth_utils import authenticate_user
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
        'is_admin': _is_portal_admin(user),
    }


@ensure_csrf_cookie
@require_http_methods(['GET'])
def csrf(request):
    return JsonResponse({'ok': True})


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
    )
    login(request, user)
    return JsonResponse({'user': _user_payload(user)}, status=201)


@require_http_methods(['POST'])
def login_view(request):
    data = _json_body(request)
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    user, err = authenticate_user(email, password)
    if err:
        return JsonResponse({'error': err}, status=401)

    login(request, user)
    return JsonResponse({'user': _user_payload(user)})


@require_http_methods(['POST'])
def logout_view(request):
    logout(request)
    return JsonResponse({'ok': True})
