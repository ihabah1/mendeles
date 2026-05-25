"""הגשת דפי HTML קלאסיים + דף סטטוס אינטגרציה."""
from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from portal.decorators import admin_required
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_GET

from .proxy import check_backends_health, legacy_services_enabled, proxy_request

BASE_DIR = Path(settings.BASE_DIR)

CLASSIC_PAGES = {
    '': 'new_stite.html',
    'index.html': 'index.html',
    'new_stite.html': 'new_stite.html',
    'auth.html': 'auth.html',
    'profile.html': 'profile.html',
    'lotto_form.html': 'lotto_form.html',
    'admin.html': 'admin.html',
}

# קישורים יחסיים בדפי HTML → נתיבי Django
_LINK_REWRITES = (
    (r'href="/auth\.html', 'href="/classic/auth.html'),
    (r'href="/profile\.html', 'href="/classic/profile.html'),
    (r'href="/new_stite\.html', 'href="/classic/new_stite.html'),
    (r'href="/lotto_form\.html', 'href="/classic/lotto_form.html'),
    (r'href="/admin\.html', 'href="/classic/admin.html'),
    (r"window\.location\.href\s*=\s*'/auth\.html", "window.location.href='/classic/auth.html"),
    (r"window\.location\.href\s*=\s*'/profile\.html", "window.location.href='/classic/profile.html"),
    (r"window\.location\.href\s*=\s*'/new_stite\.html", "window.location.href='/classic/new_stite.html"),
    (r"redirect='/profile\.html'", "redirect='/classic/profile.html'"),
    (r"redirect='/auth\.html'", "redirect='/classic/auth.html'"),
)


def _rewrite_classic_html(content: str) -> str:
    for pattern, repl in _LINK_REWRITES:
        content = re.sub(pattern, repl, content)
    banner = (
        '<div id="django-legacy-banner" style="background:#1a3a2a;border-bottom:1px solid #1db87a;'
        'padding:8px 16px;font-size:.78rem;text-align:center">'
        '<a href="/" style="color:#1db87a;font-weight:700">אתר React</a> · '
        '<a href="/manage/" style="color:#c9a84c">דשבורד Django</a> · '
        '<span style="color:#8aaabe">ממשק קלאסי (לוטו/ארנק)</span></div>'
    )
    if '<body' in content:
        content = re.sub(r'(<body[^>]*>)', r'\1' + banner, content, count=1)
    return content


@require_GET
def classic_page(request, page: str = ''):
    """דפי HTML ישנים תחת /classic/ – API נשאר ב-/auth, /lotto, /api/…"""
    name = CLASSIC_PAGES.get(page)
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
    """סטטוס שירותי Flask לדשבורד."""
    return JsonResponse({
        'enabled': legacy_services_enabled(),
        'backends': check_backends_health(),
        'classic_ui': '/classic/new_stite.html',
        'django': {
            'site': '/',
            'manage': '/manage/',
            'api_auth': '/api/auth/',
        },
    })


@admin_required
@require_GET
def integration_page(request):
    """דף ניהול: איך המערכות מחוברות."""
    from django.shortcuts import render

    health = check_backends_health()
    return render(request, 'legacy_bridge/integration.html', {
        'enabled': legacy_services_enabled(),
        'health': health,
    })


def admin_browser_entry(request):
    """GET /admin/ (דפדפן) → דשבורד Django; API נשאר ב-proxy."""
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
    return proxy_request(request, 'lotto_api', '/api/')
