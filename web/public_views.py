"""דף ראשי ציבורי – תבניות Django (לא React SPA)."""
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render


def _fetch_site_stats():
    """סטטיסטיקות לדף הבית (גיבוי אם JS נכשל)."""
    try:
        from django.test import Client

        r = Client().get('/api/stats', HTTP_HOST='localhost')
        if r.status_code == 200:
            import json

            return json.loads(r.content)
    except Exception:
        pass
    return {'total_wins': 0, 'total_prize': 0, 'active_members': 0}


def _ctx(request, **extra):
    user = request.user if request.user.is_authenticated else None
    is_admin = bool(
        user
        and user.email.lower() == settings.ADMIN_EMAIL.lower()
    )
    site_stats = extra.pop(
        'site_stats',
        {'total_wins': 0, 'total_prize': 0, 'active_members': 0},
    )
    return {
        'app_version': settings.APP_VERSION,
        'page_title': extra.pop('page_title', f'Mandeles.co.il v{settings.APP_VERSION}'),
        'active_product': extra.pop('active_product', 'lotto'),
        'site_stats': site_stats,
        'user': user,
        'is_admin': is_admin,
        **extra,
    }


def public_home(request):
    stats = _fetch_site_stats()
    return render(
        request,
        'web/lotto_home.html',
        _ctx(
            request,
            page_title='Mandeles.co.il – לוטו חכם',
            active_product='lotto',
            site_stats=stats,
        ),
    )


def public_toto(request):
    return render(
        request,
        'web/toto_home.html',
        _ctx(
            request,
            active_product='toto',
            page_title='Mandeles.co.il – טוטו חכם',
            site_stats=_fetch_site_stats(),
        ),
    )


def public_about(request):
    return render(request, 'web/about.html', _ctx(request, page_title='אודות – Mandeles.co.il'))


def public_legal(request):
    return render(request, 'web/legal.html', _ctx(request, page_title='תנאים – Mandeles.co.il'))


def public_accessibility(request):
    return render(
        request,
        'web/accessibility.html',
        _ctx(request, page_title='נגישות – Mandeles.co.il'),
    )


def public_login(request):
    if request.user.is_authenticated:
        return redirect('public-account')
    return render(request, 'web/login.html', _ctx(request, page_title='כניסה – Mandeles.co.il'))


def public_register(request):
    if request.user.is_authenticated:
        return redirect('public-account')
    return render(request, 'web/register.html', _ctx(request, page_title='הרשמה – Mandeles.co.il'))


@login_required(login_url='/login/')
def public_account(request):
    return render(
        request,
        'web/account.html',
        _ctx(request, page_title='החשבון שלי – Mandeles.co.il'),
    )
