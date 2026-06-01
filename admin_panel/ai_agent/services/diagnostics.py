"""תחקור בקשת שינוי AI – מה התבקש, אילו קבצים, ומה סוג השינוי (הוספה/מחיקה/עריכה).

נועד להצגה בדף «ניהול שינויים» כדי לבדוק למה שינוי לא עבד כמצופה.
"""
from __future__ import annotations

import re

from admin_panel.ai_agent.models import AIChangeRequest
from admin_panel.ai_agent.services.path_guard import normalize_repo_path

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


REPO_CONTENT_HEADER = '---- repo content - -'
REPO_CONTENT_FOOTER = '-- end repo --'


def build_repo_content(base_dir=None) -> dict:
    """קורא את הקבצים שה-AI רשאי לערוך (templates/, static/) ואת תוכנם.

    זהו הקונטקסט שה-AI מקבל מהריפו. מוצג בתחקור עטוף בכותרות
    «---- repo content - -» ו«-- end repo --».
    """
    from django.conf import settings

    from admin_panel.ai_agent.services.path_guard import list_allowed_files

    root = base_dir or settings.BASE_DIR
    raw = list_allowed_files(root)

    files = [
        {
            'path': rel,
            'content': content,
            'lines': content.count('\n') + 1,
            'chars': len(content),
        }
        for rel, content in raw
    ]

    blocks = [REPO_CONTENT_HEADER, '']
    for f in files:
        blocks.append(f"=== {f['path']} ({f['lines']} שורות) ===")
        blocks.append(f['content'])
        blocks.append('')
    blocks.append(REPO_CONTENT_FOOTER)

    return {
        'count': len(files),
        'total_chars': sum(f['chars'] for f in files),
        'files': files,
        'header': REPO_CONTENT_HEADER,
        'footer': REPO_CONTENT_FOOTER,
        'text': '\n'.join(blocks),
    }


def diff_segments(diff_text: str) -> list[dict]:
    """מפרק diff לתצוגת «לפני/אחרי»: לכל קובץ רשימת שורות מסומנות.

    cls של כל שורה: hunk | add (אחרי) | del (לפני) | ctx (ללא שינוי)
    """
    segments: list[dict] = []
    current: dict | None = None

    def _start(path: str = '') -> dict:
        seg = {'path': path, 'lines': []}
        segments.append(seg)
        return seg

    for line in (diff_text or '').splitlines():
        if line.startswith('diff --git'):
            m = re.match(r'diff --git a/(.+?) b/(.+)$', line)
            current = _start(normalize_repo_path(m.group(2)) if m else '')
            continue
        if current is None:
            if line.startswith('--- ') or line.startswith('@@'):
                current = _start()
            else:
                continue
        if line.startswith('+++ '):
            raw = line[4:].strip().split('\t', 1)[0]
            if raw not in ('/dev/null', '') and not current['path']:
                current['path'] = normalize_repo_path(raw)
            continue
        if (
            line.startswith('index ')
            or line.startswith('--- ')
            or line.startswith('new file')
            or line.startswith('deleted file')
            or line.startswith('similarity ')
            or line.startswith('rename ')
            or line.startswith('\\ No newline')
        ):
            continue
        if line.startswith('@@'):
            current['lines'].append({'cls': 'hunk', 'text': line})
        elif line.startswith('+'):
            current['lines'].append({'cls': 'add', 'text': line[1:]})
        elif line.startswith('-'):
            current['lines'].append({'cls': 'del', 'text': line[1:]})
        else:
            current['lines'].append({'cls': 'ctx', 'text': line[1:] if line.startswith(' ') else line})

    return [s for s in segments if s['lines']]


def site_links_for_files(files: list) -> list[dict]:
    """קישור(ים) לדף באתר שבו השינוי אמור להיראות (best-effort)."""
    from django.conf import settings

    paths = []
    for f in files or []:
        p = f.get('path') if isinstance(f, dict) else f
        if p:
            paths.append(str(p).replace('\\', '/'))

    links: list[dict] = []
    is_live = any(
        p.startswith('templates/web/')
        or p.startswith('static/css/public_site')
        or p.startswith('static/js/public_site')
        for p in paths
    )
    is_manage = any(
        p.startswith('templates/portal/') or p.startswith('static/css/portal')
        for p in paths
    )
    if is_live:
        links.append({'url': '/', 'label': 'אתר ראשי (דף הבית)'})
    if is_manage:
        prefix = str(getattr(settings, 'ADMIN_DASHBOARD_PREFIX', 'manage')).strip('/')
        links.append({'url': f'/{prefix}/', 'label': 'דשבורד ניהול'})
    return links


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
        'segments': diff_segments(diff_text),
        'site_links': site_links_for_files(files),
        'pr_url': req.pr_url or '',
        'error': req.error_message or '',
        'logs': logs,
        'images': list(req.reference_images or []),
        'publish_scope': req.publish_scope or '',
    }
