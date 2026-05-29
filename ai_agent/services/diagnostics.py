"""תחקור בקשת שינוי AI – מה התבקש, אילו קבצים, ומה סוג השינוי (הוספה/מחיקה/עריכה).

נועד להצגה בדף «ניהול שינויים» כדי לבדוק למה שינוי לא עבד כמצופה.
"""
from __future__ import annotations

import re

from ai_agent.models import AIChangeRequest
from ai_agent.services.path_guard import normalize_repo_path

# שורות לוג שמייצגות את פרשנות ה-AI (מה הבין וכיוון לאילו קבצים)
_INTERP_PREFIXES = (
    'פרשנות:',
    'מונחי חיפוש:',
    'קבצים מומלצים:',
    'מצורפות',
    'מקשר צילום',
    'נקראו',
    'נמצאו',
)

_KIND_LABELS = {
    'added': 'נוסף',
    'deleted': 'נמחק',
    'modified': 'שונה',
    'renamed': 'שינוי שם',
}


def kind_label(kind: str) -> str:
    return _KIND_LABELS.get(kind, kind)


def classify_diff_files(diff_text: str) -> list[dict]:
    """מפרק unified git diff לרשימת קבצים עם סוג השינוי וספירת שורות.

    כל פריט: {path, kind, kind_label, added, removed}
    kind ∈ added | deleted | modified | renamed
    """
    files: list[dict] = []
    current: dict | None = None

    def _new(path: str = '') -> dict:
        return {
            'path': path,
            'kind': 'modified',
            'added': 0,
            'removed': 0,
        }

    def _push() -> None:
        if current is not None:
            current['kind_label'] = kind_label(current['kind'])
            files.append(current)

    for line in (diff_text or '').splitlines():
        if line.startswith('diff --git'):
            _push()
            m = re.match(r'diff --git a/(.+?) b/(.+)$', line)
            current = _new(normalize_repo_path(m.group(2)) if m else '')
            continue

        if current is None:
            # diff ללא כותרת "diff --git" – נפתח לפי --- a/file
            if line.startswith('--- '):
                current = _new()
            else:
                continue

        if line.startswith('new file mode') or line.startswith('new file'):
            current['kind'] = 'added'
        elif line.startswith('deleted file mode') or line.startswith('deleted file'):
            current['kind'] = 'deleted'
        elif line.startswith('rename from') or line.startswith('rename to'):
            current['kind'] = 'renamed'
        elif line.startswith('--- '):
            raw = line[4:].strip().split('\t', 1)[0]
            if raw == '/dev/null':
                current['kind'] = 'added'
            elif not current['path']:
                current['path'] = normalize_repo_path(raw)
        elif line.startswith('+++ '):
            raw = line[4:].strip().split('\t', 1)[0]
            if raw == '/dev/null':
                current['kind'] = 'deleted'
            elif not current['path']:
                current['path'] = normalize_repo_path(raw)
        elif line.startswith('+') and not line.startswith('+++'):
            current['added'] += 1
        elif line.startswith('-') and not line.startswith('---'):
            current['removed'] += 1

    _push()

    # איחוד כפילויות לפי נתיב (--- ו-+++ עלולים לחזור על אותו קובץ)
    merged: dict[str, dict] = {}
    for f in files:
        key = f['path'] or f'#{len(merged)}'
        if key in merged:
            merged[key]['added'] += f['added']
            merged[key]['removed'] += f['removed']
            if f['kind'] != 'modified':
                merged[key]['kind'] = f['kind']
                merged[key]['kind_label'] = kind_label(f['kind'])
        else:
            merged[key] = f
    return list(merged.values())


def build_request_diagnostics(req: AIChangeRequest) -> dict:
    """מקבץ נתוני תחקור לבקשה אחת: טקסט המשתמש, פרשנות, קבצים ושינויים."""
    diff_text = req.result or ''
    files = classify_diff_files(diff_text)
    if not files and req.files_touched:
        files = [
            {'path': p, 'kind': 'modified', 'kind_label': kind_label('modified'),
             'added': 0, 'removed': 0}
            for p in req.files_touched
        ]

    logs = list(req.processing_log or [])
    interpretation = [
        entry.get('msg', '')
        for entry in logs
        if any((entry.get('msg', '') or '').startswith(p) for p in _INTERP_PREFIXES)
    ]

    counts = {
        'added': sum(1 for f in files if f['kind'] == 'added'),
        'deleted': sum(1 for f in files if f['kind'] == 'deleted'),
        'modified': sum(1 for f in files if f['kind'] in ('modified', 'renamed')),
        'lines_added': sum(f['added'] for f in files),
        'lines_removed': sum(f['removed'] for f in files),
    }

    return {
        'prompt': (req.prompt or '').strip(),
        'interpretation': interpretation,
        'files': files,
        'counts': counts,
        'has_diff': bool(diff_text.strip()),
        'diff_line_count': len(diff_text.splitlines()),
        'error': req.error_message or '',
        'logs': logs,
        'images': list(req.reference_images or []),
        'publish_scope': req.publish_scope or '',
    }
