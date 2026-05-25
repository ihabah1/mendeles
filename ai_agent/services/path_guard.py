"""מגבלות נתיב – רק templates/ ו-static/ מותרים לעריכה."""
from __future__ import annotations

import re
from pathlib import PurePosixPath

ALLOWED_PREFIXES = ('templates/', 'static/')

# לא מחובר ל-URL – שינוי כאן לא יופיע באתר
BLOCKED_TEMPLATE_PATHS = frozenset({
    'templates/portal/home.html',
    'templates/web/spa.html',
})

# React – לא בשימוש (האתר ב-templates/web/)
BLOCKED_PATH_PREFIXES = ('static/frontend/',)

FORBIDDEN_EXACT = frozenset({
    '.env',
    'env',
    'env.txt',
    'manage.py',
    'requirements.txt',
    'Procfile',
    'railway.toml',
})

FORBIDDEN_SUBSTRINGS = (
    'settings.py',
    'wsgi.py',
    'asgi.py',
    'urls.py',
    '/migrations/',
    'migrations/',
    'accounts/',
    'portal/views',
    'portal/forms',
    'portal/middleware',
    'web/auth_api',
    'payment',
    'stripe',
    'paypal',
    '.git/',
    '__pycache__',
    '.venv/',
    'node_modules/',
)

FORBIDDEN_PREFIXES = (
    'mandeles_portal/',
    'ai_agent/services/',
    'ai_agent/git_tools/',
)


def normalize_repo_path(path: str) -> str:
    p = path.strip().replace('\\', '/').lstrip('./')
    if p.startswith('a/') or p.startswith('b/'):
        p = p[2:]
    return PurePosixPath(p).as_posix()


def is_path_allowed(path: str) -> tuple[bool, str]:
    rel = normalize_repo_path(path)
    if not rel or rel == '.':
        return False, 'נתיב ריק'
    if rel in FORBIDDEN_EXACT:
        return False, f'קובץ אסור: {rel}'
    lower = rel.lower()
    for token in FORBIDDEN_SUBSTRINGS:
        if token in lower:
            return False, f'נתיב אסור (מכיל {token}): {rel}'
    for prefix in FORBIDDEN_PREFIXES:
        if lower.startswith(prefix):
            return False, f'תיקייה אסורה: {rel}'
    if rel in BLOCKED_TEMPLATE_PATHS:
        return False, (
            f'{rel} אינו בשימוש באתר (ארכיון). '
            'לשינוי באתר הראשי: templates/web/. לדשבורד: templates/portal/ או static/css/portal.css'
        )
    for prefix in BLOCKED_PATH_PREFIXES:
        if lower.startswith(prefix):
            return False, (
                f'{rel} – React הוסר. ערוך templates/web/ או static/css/public_site.css'
            )
    if not any(lower.startswith(prefix) for prefix in ALLOWED_PREFIXES):
        return False, f'מותר לערוך רק תחת templates/ או static/: {rel}'
    if '..' in rel.split('/'):
        return False, f'נתיב לא חוקי: {rel}'
    return True, ''


def extract_paths_from_diff(diff_text: str) -> list[str]:
    paths: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith('+++ ') or line.startswith('--- '):
            raw = line[4:].strip()
            if raw in ('/dev/null', ''):
                continue
            if '\t' in raw:
                raw = raw.split('\t', 1)[0]
            paths.append(normalize_repo_path(raw))
    return list(dict.fromkeys(paths))


def validate_diff_paths(diff_text: str) -> None:
    paths = extract_paths_from_diff(diff_text)
    if not paths:
        raise ValueError('ה-diff לא מכיל קבצים')
    blocked = []
    for path in paths:
        ok, reason = is_path_allowed(path)
        if not ok:
            blocked.append(f'{path}: {reason}')
    if blocked:
        raise ValueError('קבצים אסורים ב-diff:\n' + '\n'.join(blocked))


def list_allowed_files(base_dir) -> list[tuple[str, str]]:
    """רשימת קבצים מותרים לקונטקסט (נתיב יחסי, תוכן מקוצר)."""
    from pathlib import Path

    root = Path(base_dir)
    files: list[tuple[str, str]] = []
    max_file = 48_000
    max_total = 200_000
    total = 0
    for prefix in ALLOWED_PREFIXES:
        folder = root / prefix.rstrip('/')
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob('*')):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            ok, _ = is_path_allowed(rel)
            if not ok:
                continue
            if path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.woff', '.woff2'}:
                continue
            try:
                content = path.read_text(encoding='utf-8', errors='replace')
            except OSError:
                continue
            if len(content) > max_file:
                content = content[:max_file] + '\n... [truncated]'
            if total + len(content) > max_total:
                return files
            total += len(content)
            files.append((rel, content))
    return files
