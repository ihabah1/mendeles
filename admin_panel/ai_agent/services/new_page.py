"""יצירת דף חדש באתר הציבורי.

המנוע הרגיל יודע רק *לערוך* קבצים קיימים. כאן אנחנו תומכים ביצירת דף חדש:
בונים קובץ template חדש תחת templates/web/pages/<slug>.html (diff מסוג "קובץ חדש"),
והנתיב הגנרי /p/<slug>/ (web/public_views.public_page) מרנדר אותו אוטומטית –
כך אין צורך לגעת ב-urls.py או ב-views.py.
"""
from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings

from .diff_builder import _extract_json
from .diff_validator import DiffValidationError, validate_diff_syntax

PAGES_DIR = 'templates/web/pages'

# ביטויים שמעידים על בקשה ליצירת דף חדש (ולא עריכת דף קיים)
_TRIGGERS = (
    'דף חדש',
    'דף נוסף',
    'עמוד חדש',
    'צור דף',
    'תצור דף',
    'תיצור דף',
    'ליצור דף',
    'בנה דף',
    'תבנה דף',
    'הוסף דף',
    'להוסיף דף',
    'תוסיף דף',
    'create page',
    'create a page',
    'new page',
    'add page',
    'add a page',
)


# רמזים לכך שכתובת מסוימת מחזירה 404 והמשתמש רוצה שהדף הזה ייווצר
_NOT_FOUND_HINTS = (
    '404',
    'page not found',
    'not found',
    'לא נמצא',
    'לא קיים',
    'does not exist',
    "doesn't exist",
)

# כתובת מלאה: …/segment/  →  segment
_URL_PATH_RE = re.compile(r'https?://[^\s]+?/([a-z0-9][a-z0-9\-_]*)/?(?:\s|$)', re.IGNORECASE)
# נתיב חשוף: /segment/
_BARE_PATH_RE = re.compile(r'(?:^|\s)/([a-z0-9][a-z0-9\-_]*)/?(?:\s|$)', re.IGNORECASE)


def slug_from_prompt(prompt: str) -> str:
    """מחלץ slug מכתובת/נתיב שמופיע בבקשה (למשל מתוך הדבקת שגיאת 404)."""
    p = prompt or ''
    m = _URL_PATH_RE.search(p) or _BARE_PATH_RE.search(p)
    if m:
        return _slugify(m.group(1))
    return ''


def is_new_page_request(prompt: str) -> bool:
    p = (prompt or '').lower()
    if any(t in p for t in _TRIGGERS):
        return True
    # הדבקת 404 / כתובת שלא קיימת ⇐ ככל הנראה רוצים שדף כזה ייווצר
    if any(h in p for h in _NOT_FOUND_HINTS) and slug_from_prompt(prompt):
        return True
    return False


def _slugify(text: str) -> str:
    """משאיר אותיות לטיניות, ספרות ומקפים בלבד (slug בטוח ל-URL)."""
    text = (text or '').strip().lower()
    text = re.sub(r'[^a-z0-9]+', '-', text).strip('-')
    return text[:40]


def _unique_slug(root: Path, base: str) -> str:
    folder = Path(root) / PAGES_DIR
    slug = base or 'page'
    candidate = slug
    i = 2
    while (folder / f'{candidate}.html').exists():
        candidate = f'{slug}-{i}'
        i += 1
    return candidate


def _new_file_diff(rel_path: str, content: str) -> str:
    """unified diff ליצירת קובץ חדש (--- /dev/null) – git apply תומך בזה."""
    if not content.endswith('\n'):
        content += '\n'
    lines = content.split('\n')[:-1]  # ללא האיבר הריק האחרון
    body = ''.join('+' + ln + '\n' for ln in lines)
    return (
        f'diff --git a/{rel_path} b/{rel_path}\n'
        f'new file mode 100644\n'
        f'--- /dev/null\n'
        f'+++ b/{rel_path}\n'
        f'@@ -0,0 +1,{len(lines)} @@\n'
        f'{body}'
    )


def _render_template_file(title: str, content_html: str) -> str:
    return (
        "{% extends 'web/base_public.html' %}\n"
        "{% block content %}\n"
        f'{content_html.strip()}\n'
        '{% endblock %}\n'
    )


def _generate_page_spec(prompt: str, image_paths: list[Path] | None = None) -> str:
    import google.generativeai as genai

    api_key = getattr(settings, 'GEMINI_API_KEY', '') or ''
    model_name = getattr(settings, 'GEMINI_MODEL', 'gemini-2.5-flash')
    genai.configure(api_key=api_key)

    system = (
        'You design ONE new public web page for an existing Hebrew RTL website. '
        'Output ONLY valid JSON, no markdown, schema exactly: '
        '{"slug":"latin-hyphen-id","title":"כותרת בעברית","content_html":"<inner body HTML>"}. '
        'content_html is inserted inside {% block content %} of a template that already extends '
        'the site base (which provides the header, navigation, footer and all CSS). '
        'Therefore content_html MUST NOT contain <html>, <head>, <body>, <script>, '
        '<?php, {% extends %} or {% block %}. '
        'Reuse existing CSS classes: page-hero, page-wrap, card, about-grid, about-card, warn-box. '
        'Structure: <div class="page-hero"><h1>TITLE</h1><p>intro</p></div> then '
        '<div class="page-wrap">…content…</div>. '
        'slug must be lowercase latin letters, digits and hyphens only (no Hebrew).'
    )
    model = genai.GenerativeModel(model_name=model_name, system_instruction=system)

    try:
        gen_cfg = genai.GenerationConfig(
            temperature=0.2,
            max_output_tokens=4096,
            response_mime_type='application/json',
        )
    except Exception:
        gen_cfg = {'temperature': 0.2, 'max_output_tokens': 4096}

    parts: list = []
    if image_paths:
        from .image_attachments import _mime_for_path

        for path in image_paths:
            parts.append({'mime_type': _mime_for_path(path), 'data': path.read_bytes()})
    parts.append(f'USER REQUEST (Hebrew):\n{(prompt or "").strip()}')
    response = model.generate_content(parts, generation_config=gen_cfg)
    return (response.text or '').strip()


def build_new_page_diff(
    prompt: str,
    base_dir: Path,
    log_callback=None,
    image_paths: list[Path] | None = None,
) -> str:
    """בונה diff ליצירת דף חדש. תמיד מחזיר דף (לא נופל לעריכת קובץ קיים)."""

    def log(msg: str) -> None:
        if log_callback:
            log_callback(msg)

    title = ''
    content_html = ''
    spec_slug = ''

    api_key = getattr(settings, 'GEMINI_API_KEY', '') or ''
    if api_key:
        try:
            log('מבקש מ-Gemini מבנה דף חדש (כותרת + תוכן)…')
            raw = _generate_page_spec(prompt, image_paths=image_paths)
            data = _extract_json(raw) if raw else {}
            title = str(data.get('title') or '').strip()
            content_html = str(data.get('content_html') or data.get('html') or '').strip()
            spec_slug = _slugify(str(data.get('slug') or ''))
        except Exception as exc:  # noqa: BLE001 – נכשל? יוצרים דף בסיסי במקום לערוך קובץ קיים
            log(f'Gemini לא הצליח לייצר תוכן ({exc}) – יוצר דף בסיסי')
    else:
        log('GEMINI_API_KEY לא מוגדר – יוצר דף בסיסי')

    # אם המשתמש ציין כתובת (למשל 404 על /about-brochnik/) – ניצור את הדף באותו slug
    slug_base = slug_from_prompt(prompt) or spec_slug or _slugify(title)
    if not slug_base:
        from django.utils import timezone

        slug_base = 'page-' + timezone.now().strftime('%m%d%H%M')
    slug = _unique_slug(base_dir, slug_base)

    if not title:
        title = slug.replace('-', ' ').replace('_', ' ').strip().title() or 'דף חדש'

    if not content_html:
        content_html = (
            f'<div class="page-hero"><h1>{title}</h1></div>\n'
            f'<div class="page-wrap"><p>{(prompt or "").strip()}</p></div>'
        )

    rel = f'{PAGES_DIR}/{slug}.html'
    file_content = _render_template_file(title, content_html)

    log(f'יוצר דף חדש: {rel} · כותרת: "{title}"')
    log(f'אחרי מיזוג, הדף יהיה זמין בכתובת: /{slug}/ (וגם /p/{slug}/)')
    diff = _new_file_diff(rel, file_content)
    return validate_diff_syntax(diff)
