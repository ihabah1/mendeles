"""דף ראשי ציבורי – תבניות Django (לא React SPA)."""
from django.conf import settings
from django.shortcuts import render


def _ctx(request, **extra):
    user = request.user if request.user.is_authenticated else None
    is_admin = bool(
        user
        and user.email.lower() == settings.ADMIN_EMAIL.lower()
    )
    return {
        'app_version': settings.APP_VERSION,
        'page_title': extra.pop('page_title', f'Mandeles.co.il v{settings.APP_VERSION}'),
        'active_product': extra.pop('active_product', 'lotto'),
        'user': user,
        'is_admin': is_admin,
        **extra,
    }


def public_home(request):
    return render(request, 'web/home.html', _ctx(request, page_title='Mandeles.co.il – לוטו חכם'))


def public_toto(request):
    return render(
        request,
        'web/home.html',
        _ctx(request, active_product='toto', page_title='Mandeles.co.il – טוטו חכם'),
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
    return render(request, 'web/login.html', _ctx(request, page_title='כניסה – Mandeles.co.il'))


def public_register(request):
    return render(request, 'web/register.html', _ctx(request, page_title='הרשמה – Mandeles.co.il'))
