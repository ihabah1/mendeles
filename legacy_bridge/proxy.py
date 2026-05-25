"""פרוקסי לשרתי Flask המקומיים – אותה לוגיקה כמו router.py בתוך Django."""
from __future__ import annotations

import logging
from urllib.parse import urljoin

import requests
from django.conf import settings
from django.http import HttpResponse, JsonResponse

log = logging.getLogger(__name__)

SKIP_REQ_HEADERS = frozenset({'host', 'content-length', 'connection'})
SKIP_RESP_HEADERS = frozenset({'content-encoding', 'transfer-encoding', 'connection'})


def _backend_urls() -> dict[str, str]:
    return {
        'engine': getattr(settings, 'LEGACY_ENGINE_URL', 'http://127.0.0.1:5001'),
        'auth': getattr(settings, 'LEGACY_AUTH_URL', 'http://127.0.0.1:5002'),
        'wallet': getattr(settings, 'LEGACY_WALLET_URL', 'http://127.0.0.1:5003'),
        'lotto_api': getattr(settings, 'LEGACY_LOTTO_API_URL', 'http://127.0.0.1:5000'),
    }


def legacy_services_enabled() -> bool:
    return getattr(settings, 'LEGACY_SERVICES_ENABLED', True)


def proxy_request(request, backend_key: str, path_prefix: str) -> HttpResponse:
    if not legacy_services_enabled():
        return JsonResponse(
            {'error': 'שירותי לוטו מושבתים (LEGACY_SERVICES_ENABLED=false)'},
            status=503,
        )

    base = _backend_urls().get(backend_key, '').rstrip('/')
    if not base:
        return JsonResponse({'error': f'backend לא מוגדר: {backend_key}'}, status=500)

    subpath = request.path.removeprefix(path_prefix).lstrip('/')
    target = urljoin(base + '/', subpath)
    if request.META.get('QUERY_STRING'):
        target = f'{target}?{request.META["QUERY_STRING"]}'

    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in SKIP_REQ_HEADERS
    }

    try:
        resp = requests.request(
            method=request.method,
            url=target,
            headers=headers,
            data=request.body,
            cookies=request.COOKIES,
            timeout=int(getattr(settings, 'LEGACY_PROXY_TIMEOUT', 120)),
            allow_redirects=False,
        )
    except requests.exceptions.ConnectionError:
        log.warning('Legacy backend down: %s -> %s', backend_key, target)
        return JsonResponse(
            {
                'error': f'שרת {backend_key} לא פעיל',
                'hint': 'הפעל: python start_all.py או .\run.ps1 -Legacy',
                'target': target,
            },
            status=503,
        )
    except requests.exceptions.Timeout:
        return JsonResponse({'error': 'תם הזמן לשרת הלוטו'}, status=504)

    out_headers = {
        k: v for k, v in resp.headers.items()
        if k.lower() not in SKIP_RESP_HEADERS
    }
    return HttpResponse(
        resp.content,
        status=resp.status_code,
        headers=out_headers,
        content_type=resp.headers.get('Content-Type', 'application/octet-stream'),
    )


def check_backends_health() -> dict:
    """תאימות לאחור – משתמש ב-health_status המלא."""
    from .health_status import check_backends_health as _full_check

    return _full_check()
