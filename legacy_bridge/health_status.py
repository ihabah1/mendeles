"""בדיקת בריאות שירותים – דרך Django (פרוקסי) ו/או Flask ישיר."""
from __future__ import annotations

import socket
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.test import Client

from .proxy import _backend_urls, legacy_services_enabled


def _port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _parse_host_port(base_url: str) -> tuple[str, int]:
    p = urlparse(base_url)
    host = p.hostname or '127.0.0.1'
    port = p.port or (443 if p.scheme == 'https' else 80)
    return host, port


def _probe_url(url: str, timeout: float = 2.0) -> dict:
    try:
        r = requests.get(url, timeout=timeout)
        return {'ok': r.status_code < 500, 'code': r.status_code}
    except Exception as exc:
        return {'ok': False, 'error': str(exc)[:120]}


def _probe_django_path(path: str) -> dict:
    try:
        client = Client()
        r = client.get(path, HTTP_HOST='localhost')
        # 401/403 = שירות חי, רק דורש הרשאה
        ok = r.status_code < 500
        return {'ok': ok, 'code': r.status_code, 'via': 'django'}
    except Exception as exc:
        return {'ok': False, 'error': str(exc)[:120], 'via': 'django'}


# נתיבי בדיקה לכל backend (לא כולם /health)
_BACKEND_HEALTH_PATHS = {
    'engine': '/engine/health',
    'auth': '/auth/me',
    'wallet': '/api/stats',
    'lotto_api': '/api/health',
}


def check_backends_health() -> dict:
    """
    בודק שירותי לוטו:
    1) פורט פתוח על localhost
    2) HTTP ישיר ל-Flask
    3) דרך נתיבי הפרוקסי של Django (אותו תהליך ב-Railway)

    שירות שכובה ידנית מסומן state='disabled' (לא דגל אדום של תקלה).
    """
    from .service_registry import disabled_services

    out: dict[str, dict] = {}
    if not legacy_services_enabled():
        for name in _BACKEND_HEALTH_PATHS:
            out[name] = {'ok': False, 'disabled': True, 'state': 'disabled', 'disabled_manual': True}
        return out

    disabled = disabled_services()
    for name, base in _backend_urls().items():
        host, port = _parse_host_port(base)
        if name in disabled:
            out[name] = {
                'ok': False,
                'state': 'disabled',
                'disabled_manual': True,
                'port': port,
            }
            continue

        path = _BACKEND_HEALTH_PATHS.get(name, '/health')
        port_up = _port_open(host, port)
        direct = _probe_url(f'{base.rstrip("/")}{path}')
        via_django = _probe_django_path(path)

        ok = port_up or direct.get('ok') or via_django.get('ok')
        out[name] = {
            'ok': ok,
            'state': 'up' if ok else 'down',
            'disabled_manual': False,
            'port_up': port_up,
            'direct': direct,
            'django': via_django,
            'port': port,
        }
    return out


def check_django_platform() -> dict:
    """שירותי ליבה שתמיד רצים בתוך Django."""
    client = Client()
    checks = {
        'public_site': '/',
        'api_auth': '/api/auth/csrf/',
        'manage': '/manage/login/',
    }
    out = {}
    for key, path in checks.items():
        try:
            r = client.get(path, HTTP_HOST='localhost')
            out[key] = {'ok': r.status_code < 500, 'code': r.status_code}
        except Exception as exc:
            out[key] = {'ok': False, 'error': str(exc)[:80]}
    return out


def integration_dashboard_context() -> dict:
    """הקשר מלא לדף /manage/integration/."""
    from .service_registry import SERVICE_KEYS, SERVICES

    legacy = check_backends_health()
    django = check_django_platform()
    legacy_on = legacy_services_enabled()

    services = []
    unavailable_pages = []
    for key in SERVICE_KEYS:
        reg = SERVICES[key]
        item = legacy.get(key, {})
        ok = bool(item.get('ok'))
        disabled_manual = bool(item.get('disabled_manual'))
        state = item.get('state') or ('up' if ok else 'down')
        services.append({
            'key': key,
            'label': reg['label'],
            'port': item.get('port') or reg['port'],
            'check_path': reg['check_path'],
            'pages': reg['pages'],
            'ok': ok,
            'disabled_manual': disabled_manual,
            'state': state,
        })
        if not ok:
            reason = 'כובה ידנית' if disabled_manual else 'לא מגיב'
            for pg in reg['pages']:
                unavailable_pages.append({
                    **pg,
                    'service': key,
                    'service_label': reg['label'],
                    'reason': reason,
                    'disabled_manual': disabled_manual,
                })

    # "פעיל" מתייחס רק לשירותים שלא כובו ידנית – כיבוי מכוון אינו תקלה
    enabled_items = [v for v in legacy.values() if not v.get('disabled_manual')]
    legacy_all_ok = legacy_on and bool(enabled_items) and all(v.get('ok') for v in enabled_items)
    legacy_partial = legacy_on and any(v.get('ok') for v in legacy.values())

    return {
        'enabled': legacy_on,
        'health': legacy,
        'services': services,
        'unavailable_pages': unavailable_pages,
        'django_health': django,
        'legacy_all_ok': legacy_all_ok,
        'legacy_partial': legacy_partial,
        'auto_start': getattr(settings, 'LEGACY_AUTO_START', True),
    }
