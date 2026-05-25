"""פרוקסי API לוטו + הפניות דפי HTML ישנים ל-Django."""
from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_GET
from portal.decorators import admin_required

from .proxy import check_backends_health, legacy_services_enabled, proxy_request

BASE_DIR = Path(settings.BASE_DIR)

# דפים שהועברו ל-Django – הפניה קבועה
_CLASSIC_REDIRECTS = {
    '': '/',
    'index.html': '/',
    'new_stite.html': '/',
    'auth.html': '/login/',
}

# דפים תפעוליים שעדיין HTML סטטי (ללא React) – מוגשים בלי באנר
_CLASSIC_STATIC_PAGES = {
    'profile.html': 'profile.html',
    'lotto_form.html': 'lotto_form.html',
    'admin.html': 'admin.html',
}

_LINK_REWRITES = (
    (r'href="/auth\.html', 'href="/login/'),
    (r'href="/profile\.html', 'href="/classic/profile.html'),
    (r'href="/new_stite\.html', 'href="/'),
    (r'href="/lotto_form\.html', 'href="/classic/lotto_form.html'),
    (r'href="/admin\.html', 'href="/classic/admin.html'),
    (r"window\.location\.href\s*=\s*'/auth\.html", "window.location.href='/login/'"),
    (r"window\.location\.href\s*=\s*'/profile\.html", "window.location.href='/classic/profile.html'"),
    (r"window\.location\.href\s*=\s*'/new_stite\.html", "window.location.href='/'"),
    (r"redirect='/profile\.html'", "redirect='/classic/profile.html'"),
    (r"redirect='/auth\.html'", "redirect='/login/'"),
)


def _rewrite_classic_html(content: str) -> str:
    for pattern, repl in _LINK_REWRITES:
        content = re.sub(pattern, repl, content)
    return content


@require_GET
def classic_page(request, page: str = ''):
    """דפי HTML ישנים: רובם מופנים ל-Django; תפעוליים נשארים תחת /classic/."""
    if page in _CLASSIC_REDIRECTS:
        target = _CLASSIC_REDIRECTS[page]
        qs = request.META.get('QUERY_STRING', '')
        if qs:
            target = f'{target}?{qs}' if '?' not in target else f'{target}&{qs}'
        return redirect(target, permanent=True)

    name = _CLASSIC_STATIC_PAGES.get(page)
    if not name:
        raise Http404
    path = BASE_DIR / name
    if not path.is_file():
        raise Http404
    text = path.read_text(encoding='utf-8', errors='replace')
    if name.endswith('.html'):
        text = _rewrite_classic_html(text)
        return HttpResponse(text, content_type='text/html; charset=utf-8')
    return FileResponse(path.open('rb'))


@require_GET
def integration_status(request):
    return JsonResponse({
        'enabled': legacy_services_enabled(),
        'backends': check_backends_health(),
        'site': '/',
        'django': {
            'site': '/',
            'manage': '/manage/',
            'api_auth': '/api/auth/',
        },
    })


@admin_required
@require_GET
def integration_page(request):
    from django.shortcuts import render

    health = check_backends_health()
    return render(request, 'legacy_bridge/integration.html', {
        'enabled': legacy_services_enabled(),
        'health': health,
    })


def admin_browser_entry(request):
    return redirect('/manage/customers/')


def proxy_auth(request, path=''):
    return proxy_request(request, 'auth', '/auth/')


def proxy_lotto(request, path=''):
    return proxy_request(request, 'wallet', '/lotto/')


def proxy_wallet_admin(request, path=''):
    return proxy_request(request, 'wallet', '/admin/')


def proxy_engine(request, path=''):
    return proxy_request(request, 'engine', '/engine/')


def proxy_lotto_api(request, path=''):
    return proxy_request(request, 'lotto_api', '/api/' + path)
