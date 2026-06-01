"""מקור אמת יחיד לשירותי ה-Flask: פורט, נתיב בדיקה, סקריפט, ותלויות.

`pages` = הדפים/היכולות שתלויים בשירות ויהפכו ללא-זמינים אם הוא כבוי.
"""
from __future__ import annotations

SERVICES: dict[str, dict] = {
    'engine': {
        'label': 'מנוע טוטו (engine)',
        'script': 'beckend_toto.py',
        'port': 5001,
        'check_path': '/engine/health',
        'pages': [
            {'label': 'טוטו – מנוע ניתוח', 'url': '/toto/'},
            {'label': 'נתיבי /engine/', 'url': '/engine/'},
        ],
    },
    'auth': {
        'label': 'התחברות קלאסית (auth)',
        'script': 'auth_server.py',
        'port': 5002,
        'check_path': '/auth/me',
        'pages': [
            {'label': 'התחברות קלאסית', 'url': '/auth/'},
            {'label': 'פרופיל קלאסי', 'url': '/classic/profile.html'},
        ],
    },
    'wallet': {
        'label': 'ארנק / הזמנות (wallet)',
        'script': 'wallet_server.py',
        'port': 5003,
        'check_path': '/api/stats',
        'pages': [
            {'label': 'ארנק וחיוב', 'url': '/lotto/'},
            {'label': 'ניהול ארנק (admin)', 'url': '/admin/'},
        ],
    },
    'lotto_api': {
        'label': 'API לוטו (api)',
        'script': 'server.py',
        'port': 5000,
        'check_path': '/api/health',
        'pages': [
            {'label': 'בדיקת צירוף לוטו', 'url': '/api/check'},
            {'label': 'נתוני הגרלה', 'url': '/api/next-draw'},
            {'label': 'סטטיסטיקות לוטו', 'url': '/api/stats'},
        ],
    },
}

SERVICE_KEYS = tuple(SERVICES.keys())


def service_label(key: str) -> str:
    return (SERVICES.get(key) or {}).get('label', key)


def service_pages(key: str) -> list[dict]:
    return list((SERVICES.get(key) or {}).get('pages', []))


def _state_table_exists() -> bool:
    """False בזמן migrate לפני יצירת הטבלה – לא לגעת ב-DB מוקדם מדי."""
    from django.db import connection

    try:
        from .models import LegacyServiceState

        return LegacyServiceState._meta.db_table in connection.introspection.table_names()
    except Exception:
        return False


def disabled_services() -> set[str]:
    """מזהי שירותים שכובו ידנית מהדשבורד."""
    if not _state_table_exists():
        return set()
    from .models import LegacyServiceState

    return set(
        LegacyServiceState.objects.filter(enabled=False).values_list('service_key', flat=True),
    )


def is_service_enabled(key: str) -> bool:
    return key not in disabled_services()


def set_service_enabled(key: str, enabled: bool, note: str = '') -> None:
    from .models import LegacyServiceState

    LegacyServiceState.objects.update_or_create(
        service_key=key,
        defaults={'enabled': enabled, 'note': note[:200]},
    )
