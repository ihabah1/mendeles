"""
אינדוקס תוכן האתר + פרשנות בקשות שינוי בשפה פשוטה (עברית).

מאפשר למנהל לכתוב למשל: "תוריד את המילה version מהדף הראשי"
בלי לציין נתיבי קבצים.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .path_guard import list_allowed_files

# אזורים לוגיים → תוויות בעברית (למנהל) + קבצים אופייניים
ZONES: dict[str, dict] = {
    'public_home': {
        'label': 'דף ראשי (לוטו)',
        'keywords': (
            'דף ראשי', 'דף הבית', 'דף בית', 'באתר', 'באתר הראשי', 'ראשי',
            'homepage', 'home page', 'לוטו', 'מנדל', 'אסטרטגיית',
        ),
        'files': (
            'templates/web/lotto_home.html',
            'templates/web/home.html',
            'templates/web/partials/lotto_panel.html',
            'templates/web/base_public.html',
            'static/css/public_site.css',
            'static/js/public_site.js',
        ),
    },
    'public_nav': {
        'label': 'סרגל עליון / תפריט',
        'keywords': (
            'סרגל', 'תפריט', 'ניווט', 'למעלה', 'header', 'nav', 'לוגו', 'logo',
            'version', 'גרסה', 'v2', 'מצב הדגמה', 'הדגמה', 'demo',
            'יופי', 'שלום', 'ברכה', 'greeting', 'nav-greeting', 'שם משתמש', 'username',
        ),
        'files': ('templates/web/base_public.html',),
    },
    'public_toto': {
        'label': 'דף טוטו',
        'keywords': ('טוטו', 'toto', 'משחקים', '1x2'),
        'files': (
            'templates/web/partials/toto_panel.html',
            'templates/web/home.html',
        ),
    },
    'public_footer': {
        'label': 'פוטר / תחתית',
        'keywords': ('פוטר', 'תחתית', 'footer', 'זכויות'),
        'files': ('templates/web/base_public.html',),
    },
    'public_about': {
        'label': 'דף אודות',
        'keywords': ('אודות', 'about'),
        'files': ('templates/web/about.html',),
    },
    'public_legal': {
        'label': 'תנאים / מדיניות',
        'keywords': ('תנאים', 'מדיניות', 'legal', 'פרטיות'),
        'files': ('templates/web/legal.html',),
    },
    'public_login': {
        'label': 'כניסה / הרשמה',
        'keywords': ('כניסה', 'הרשמה', 'login', 'register'),
        'files': ('templates/web/login.html', 'templates/web/register.html'),
    },
    'manage': {
        'label': 'דשבורד ניהול',
        'keywords': (
            'ניהול', 'דשבורד', 'manage', 'לקוחות', 'הזמנות', 'פורטל',
            'סרגל', 'תפריט צד', 'sidebar', 'משתמשים', 'הזמנות', 'לוטו', 'טוטו',
            'תור', 'שינויים', 'אינטגרציה',
        ),
        'files': (
            'templates/portal/base_dashboard.html',
            'static/css/portal.css',
        ),
    },
}

_ACTION_REMOVE = re.compile(
    r'(?:תוריד|הסר|מחק|הורד|בטל|תסיר|תמחק|להסיר|להוריד|remove|delete)\s+',
    re.IGNORECASE,
)
_ACTION_REPLACE = re.compile(
    r'(?:שנה|החלף|עדכן|תשנה|תחליף|change|replace)\s+',
    re.IGNORECASE,
)
_INSTEAD_OF = re.compile(
    r'במקום\s+(?:המילה|הטקסט|הכיתוב|מילה)?\s*'
    r'(?:["\'«»]([^"\'«»]+)["\'«»]|([\u0590-\u05FFa-zA-Z0-9._-]+))\s+'
    r'(?:שיופיע|יופיע|הצג|תציג|תראה|שיציג|להציג|שם\s+)',
    re.IGNORECASE,
)
_SHOW_INSTEAD = re.compile(
    r'(?:שיופיע|יופיע|הצג|תציג|תראה|שיציג|להציג)\s+(?:רק\s+)?(?:את\s+)?(?:ה)?(.+?)(?:\s+בסרגל|\s+בתפריט|\s+בדף|\.|$)',
    re.IGNORECASE,
)
_QUOTED = re.compile(r'["\'«»]([^"\'«»]+)["\'«»]')
_THE_WORD = re.compile(
    r'(?:את\s+)?(?:המילה|הטקסט|הכיתוב|המשפט|מילה)?\s*["\']?([^"\']+?)["\']?\s+'
    r'(?:מה|מ|ב|בתוך|בתחתית|בסרגל|בדף)',
    re.IGNORECASE,
)
_STRIP_TAGS = re.compile(r'<[^>]+>')
_DJANGO_VAR = re.compile(r'\{\{[^}]+\}\}|\{%[^%]+%\}')

# ביטויים בעברית → משתני Django בתבנית
_DJANGO_PLACEHOLDERS: dict[str, str] = {
    'שם משתמש': '{{ user.username }}',
    'שם המשתמש': '{{ user.username }}',
    'username': '{{ user.username }}',
    'שם מלא': '{{ user.get_full_name|default:user.username }}',
    'אימייל': '{{ user.email }}',
    'מייל': '{{ user.email }}',
}

_INTENT_HINTS: dict[str, str] = {
    'add_page': (
        'כוונה: דף/עמוד חדש באתר.\n'
        '- צור templates/web/<slug>.html שמרחיב base_public.html.\n'
        '- הוסף קישור ב-templates/web/base_public.html (nav-links או תפריט).\n'
        '- URL (/path/) דורש שורה ב-web/urls.py – AI לא יכול לערוך Python; '
        'ציין בראש התבנית HTML comment עם הנתיב המבוקש.\n'
    ),
    'api_page': (
        'כוונה: הצגת נתונים מ-API.\n'
        '- fetch ב-static/js/public_site.js או בלוק {% block extra_js %} בתבנית.\n'
        '- השתמש בנתיבי פרוקסי קיימים: /api/…, /engine/…, /auth/me (מחובר).\n'
        '- הצג loading + שגיאה בעברית.\n'
    ),
    'user_page': (
        'כוונה: תוכן לפי משתמש מחובר.\n'
        '- בתבנית: {% if user %} … {% else %} … {% endif %}.\n'
        '- שדות: {{ user.username }}, {{ user.email }}, is_admin.\n'
        '- לנתוני ארנק/פרופיל: fetch ל-/auth/me או /classic/profile.html.\n'
    ),
}

_INDEX_SKIP = frozenset({
    'templates/web/spa.html',
    'templates/portal/home.html',
})


@dataclass
class TextSnippet:
    file: str
    line: int
    text: str
    zone: str
    raw_line: str = ''

    @property
    def zone_label(self) -> str:
        return ZONES.get(self.zone, {}).get('label', self.zone)


@dataclass
class ResolvedRequest:
    """תוצאת פרשנות בקשה."""
    original_prompt: str
    action: str  # remove | replace | change | unknown
    intent: str = 'generic'  # replace_text | remove_text | add_page | api_page | user_page | generic
    search_terms: list[str] = field(default_factory=list)
    replace_from: str = ''
    replace_to: str = ''
    zones: list[str] = field(default_factory=list)
    target_files: list[str] = field(default_factory=list)
    matched_snippets: list[TextSnippet] = field(default_factory=list)
    interpretation_he: str = ''
    enriched_prompt: str = ''

    def to_log_line(self) -> str:
        base = self.interpretation_he or 'לא זוהתה כוונה מדויקת'
        if self.replace_from and self.replace_to:
            return f'{base} → «{self.replace_from}» ל«{self.replace_to[:40]}»'
        return base


def _guess_zone_for_path(rel: str) -> str:
    r = rel.replace('\\', '/').lower()
    if 'portal/' in r:
        return 'manage'
    if 'toto_panel' in r:
        return 'public_toto'
    if 'lotto_panel' in r or r.endswith('web/home.html'):
        return 'public_home'
    if 'base_public' in r:
        return 'public_nav'
    if 'about' in r:
        return 'public_about'
    if 'legal' in r:
        return 'public_legal'
    if 'login' in r or 'register' in r:
        return 'public_login'
    if 'public_site.css' in r:
        return 'public_home'
    return 'public_home'


def _extract_visible_strings(line: str) -> list[str]:
    """מחלץ מחרוזות גלויות משורת HTML/CSS."""
    if '<script' in line.lower() or '<style' in line.lower():
        return []
    plain = _STRIP_TAGS.sub(' ', line)
    plain = _DJANGO_VAR.sub(' ', plain)
    plain = re.sub(r'\s+', ' ', plain).strip()
    out: list[str] = []
    if len(plain) >= 2:
        out.append(plain)
    for m in _DJANGO_VAR.finditer(line):
        v = m.group(0).strip()
        if 'app_version' in v or 'version' in v.lower():
            out.append('app_version (מספר גרסה בסרגל)')
        else:
            out.append(v)
    if 'app_version' in line and 'v{{' in line.replace(' ', ''):
        out.append('v{{ app_version }}')
    if 'version' in line.lower() and 'app-version' in line.lower():
        out.append('meta app-version')
    return out


def _should_index(rel: str) -> bool:
    return rel.replace('\\', '/').lower() not in _INDEX_SKIP


def build_site_index(base_dir: Path) -> list[TextSnippet]:
    """סורק קבצים מותרים ובונה רשימת קטעי טקסט לעריכה."""
    snippets: list[TextSnippet] = []
    for rel, content in list_allowed_files(base_dir):
        if not _should_index(rel):
            continue
        zone = _guess_zone_for_path(rel)
        for i, line in enumerate(content.splitlines(), start=1):
            for text in _extract_visible_strings(line):
                if len(text) < 2:
                    continue
                snippets.append(
                    TextSnippet(
                        file=rel,
                        line=i,
                        text=text,
                        zone=zone,
                        raw_line=line.strip()[:200],
                    ),
                )
    return snippets


def _django_placeholder(phrase: str) -> str:
    p = phrase.strip().lower()
    for key, val in _DJANGO_PLACEHOLDERS.items():
        if key.lower() in p or p == key.lower():
            return val
    return ''


def _extract_replace_pair(prompt: str, prompt_l: str) -> tuple[str, str]:
    """מחלץ זוג החלפה: במקום X → Y (כולל שם משתמש)."""
    old, new = '', ''

    m = _INSTEAD_OF.search(prompt)
    if m:
        old = (m.group(1) or m.group(2) or '').strip().strip('"\'«»')
        rest = prompt[m.end():]
        m2 = _SHOW_INSTEAD.search(rest) or _SHOW_INSTEAD.search(prompt)
        if m2:
            new = m2.group(1).strip().strip('"\'«»')

    if not old and 'יופי' in prompt:
        old = 'יופי'
    if not new and any(
        w in prompt_l for w in ('שם משתמש', 'username', 'שם המשתמש')
    ):
        new = _django_placeholder('שם משתמש')

    # «שנה את X ל-Y»
    m3 = re.search(
        r'(?:שנה|החלף)\s+את\s+["\'«»]?([^"\'«»]+)["\'«»]?\s+ל(?:־|\-)?["\'«»]?([^"\'«»]+)["\'«»]?',
        prompt,
        re.IGNORECASE,
    )
    if m3 and not old:
        old, new = m3.group(1).strip(), m3.group(2).strip()

    if new and not new.startswith('{{'):
        ph = _django_placeholder(new)
        if ph:
            new = ph

    return old, new


def _detect_intent(prompt: str, prompt_l: str, action: str) -> str:
    if any(
        w in prompt_l
        for w in (
            'דף חדש', 'עמוד חדש', 'להוסיף דף', 'הוסף דף', 'דף שיציג',
            'עמוד שיציג', 'צור דף', 'new page',
        )
    ):
        if any(w in prompt_l for w in ('api', 'מכתובת', 'endpoint', 'fetch', 'קריאה')):
            return 'api_page'
        if any(w in prompt_l for w in ('משתמש', 'מחובר', 'אישי', 'פרופיל')):
            return 'user_page'
        return 'add_page'
    if any(
        w in prompt_l
        for w in ('api', 'מכתובת', 'endpoint', '/api/', 'fetch', 'json')
    ) and any(w in prompt_l for w in ('דף', 'עמוד', 'הצג', 'תציג', 'יופיע')):
        return 'api_page'
    if any(
        w in prompt_l
        for w in ('משתמש', 'משתמשים', 'מחובר', 'username', 'שם משתמש', 'נתיבים')
    ) and action in ('replace', 'change'):
        return 'user_page'
    if action == 'replace' or 'במקום' in prompt:
        return 'replace_text'
    if action == 'remove':
        return 'remove_text'
    return 'generic'


def _detect_zones(prompt_l: str) -> list[str]:
    found: list[str] = []
    for zone_id, meta in ZONES.items():
        if any(kw in prompt_l for kw in meta['keywords']):
            found.append(zone_id)
    if not found:
        if any(w in prompt_l for w in ('אתר', 'ראשי', 'חיצוני', 'ציבורי')):
            found.append('public_home')
            found.append('public_nav')
    return found or ['public_home', 'public_nav']


def _detect_action(prompt: str) -> str:
    if _ACTION_REMOVE.search(prompt):
        return 'remove'
    if _ACTION_REPLACE.search(prompt) or 'במקום' in prompt:
        return 'replace'
    if any(
        w in prompt
        for w in ('שיופיע', 'יופיע', 'הצג', 'תציג', 'תראה')
    ) and any(w in prompt for w in ('במקום', 'יופי', 'שם משתמש', 'username')):
        return 'replace'
    if any(w in prompt for w in ('שנה', 'החלף', 'עדכן', 'גדול', 'קטן', 'צבע')):
        return 'change'
    return 'unknown'


def _extract_search_terms(prompt: str, prompt_l: str) -> list[str]:
    terms: list[str] = []

    for m in _QUOTED.finditer(prompt):
        terms.append(m.group(1).strip())

    m = _THE_WORD.search(prompt)
    if m:
        t = m.group(1).strip()
        if len(t) <= 40 and 'תוריד' not in t and 'הסר' not in t:
            terms.append(t)

    for pat in (
        r'(?:המילה|מילה|טקסט|כיתוב)\s+["\']?([a-zA-Z0-9\u0590-\u05FF._ -]{2,30})',
        r'(?:את|ה)\s+["\']?([a-zA-Z][a-zA-Z0-9._-]{1,20})',
        r'\b(version)\b',
        r'(גרסה)',
    ):
        for hit in re.finditer(pat, prompt, re.IGNORECASE):
            t = (hit.group(1) if hit.lastindex else hit.group(0)).strip()
            if t and len(t) >= 2 and t not in ('את', 'ה', 'מ', 'ב'):
                terms.append(t)

    if 'version' in prompt_l or 'גרסה' in prompt_l:
        terms.extend(['version', 'app_version', 'v{{ app_version }}', 'גרסה'])

    if 'מצב הדגמה' in prompt or 'הדגמה' in prompt:
        terms.append('מצב הדגמה')

    if 'יופי' in prompt:
        terms.append('יופי')
        terms.append('nav-greeting')

    old, new = _extract_replace_pair(prompt, prompt_l)
    if old:
        terms.append(old)
    if new and not new.startswith('{{'):
        terms.append(new)

    # ניקוי מונחים מזוהמים (למשל "version מהדף הראשי")
    cleaned: list[str] = []
    for t in terms:
        t = t.strip()
        if 'מהדף' in t or 'מהסרגל' in t or 'תוריד' in t or 'הסר' in t:
            for part in re.findall(r'[a-zA-Z][a-zA-Z0-9._-]*', t):
                cleaned.append(part)
            for part in re.findall(r'[\u0590-\u05FF]{2,}', t):
                if part not in ('מהדף', 'הראשי', 'הסרגל', 'תוריד', 'הסר', 'את', 'המילה'):
                    cleaned.append(part)
            continue
        cleaned.append(t)

    seen: set[str] = set()
    out: list[str] = []
    for t in cleaned:
        tl = t.lower()
        if tl not in seen and len(t) >= 2:
            seen.add(tl)
            out.append(t)
    return out


def _rank_files(zones: list[str], snippets: list[TextSnippet], terms: list[str]) -> list[str]:
    scores: dict[str, float] = {}
    for z in zones:
        for f in ZONES.get(z, {}).get('files', ()):
            scores[f] = scores.get(f, 0) + 10.0
    for sn in snippets:
        for term in terms:
            tl = term.lower()
            if tl in sn.text.lower() or tl in sn.raw_line.lower():
                scores[sn.file] = scores.get(sn.file, 0) + 20.0
    ordered = sorted(scores.keys(), key=lambda p: -scores[p])
    return ordered


def _match_snippets(
    snippets: list[TextSnippet],
    zones: list[str],
    terms: list[str],
    limit: int = 12,
) -> list[TextSnippet]:
    hits: list[tuple[float, TextSnippet]] = []
    for sn in snippets:
        if zones and sn.zone not in zones:
            continue
        score = 0.0
        blob = f'{sn.text} {sn.raw_line}'.lower()
        for term in terms:
            tl = term.lower()
            if tl in blob:
                score += 10.0
            if tl == 'version' and ('app_version' in blob or 'version' in blob):
                score += 15.0
        if score > 0:
            hits.append((score, sn))
    hits.sort(key=lambda x: -x[0])
    return [sn for _, sn in hits[:limit]]


def resolve_request(prompt: str, base_dir: Path) -> ResolvedRequest:
    """מפרש בקשה בשפה חופשית ומחזיר קבצים + הקשר."""
    prompt = (prompt or '').strip()
    prompt_l = prompt.lower()
    action = _detect_action(prompt)
    replace_from, replace_to = _extract_replace_pair(prompt, prompt_l)
    if replace_from and action == 'unknown':
        action = 'replace'
    intent = _detect_intent(prompt, prompt_l, action)
    zones = _detect_zones(prompt_l)
    if intent in ('add_page', 'api_page', 'user_page'):
        for z in ('public_home', 'public_nav'):
            if z not in zones:
                zones.append(z)
    terms = _extract_search_terms(prompt, prompt_l)

    index = build_site_index(base_dir)
    matched = _match_snippets(index, zones, terms)
    target_files = _rank_files(zones, matched, terms)

    zone_labels = ', '.join(ZONES[z]['label'] for z in zones[:3])
    term_str = ', '.join(f'«{t}»' for t in terms[:4]) if terms else '—'

    if action == 'remove':
        interp = f'הסרת תוכן ({term_str}) מ{zone_labels}'
    elif action == 'replace' and replace_from:
        interp = f'החלפת «{replace_from}» ב{zone_labels}'
        if replace_to:
            interp += f' → {replace_to[:50]}'
    elif action == 'replace':
        interp = f'החלפת תוכן ({term_str}) ב{zone_labels}'
    elif intent == 'add_page':
        interp = f'הוספת דף חדש – {zone_labels}'
    elif intent == 'api_page':
        interp = f'דף/אזור עם נתוני API – {zone_labels}'
    elif intent == 'user_page':
        interp = f'תוכן לפי משתמש – {zone_labels}'
    else:
        interp = f'שינוי ב{zone_labels}' + (f' – חיפוש: {term_str}' if terms else '')

    snippet_block = []
    for sn in matched[:8]:
        snippet_block.append(
            f'- [{sn.zone_label}] {sn.file}:{sn.line} → "{sn.text[:80]}"',
        )
    if not snippet_block and terms:
        for sn in index:
            for term in terms:
                if term.lower() in sn.raw_line.lower():
                    snippet_block.append(
                        f'- [{sn.zone_label}] {sn.file}:{sn.line} → שורה: {sn.raw_line[:100]}',
                    )
                    if len(snippet_block) >= 8:
                        break
            if len(snippet_block) >= 8:
                break

    files_hint = '\n'.join(f'  • {f}' for f in target_files[:6])
    enriched = (
        f'בקשת משתמש (שפה פשוטה): {prompt}\n\n'
        f'פרשנות מערכת: {interp}\n'
        f'פעולה: {action}\n'
        f'אזורים: {zone_labels}\n'
        f'קבצים מומלצים:\n{files_hint}\n'
    )
    if snippet_block:
        enriched += '\nמיקומים שזוהו באינדוקס:\n' + '\n'.join(snippet_block) + '\n'
    if replace_from:
        enriched += f'\nהחלפה מבוקשת: הסר/החלף «{replace_from}»'
        if replace_to:
            enriched += f' → השאר/הצג: {replace_to}\n'
    if intent in _INTENT_HINTS:
        enriched += '\n' + _INTENT_HINTS[intent]
    enriched += (
        '\nהוראה: בצע את השינוי בקבצים המומלצים בלבד. '
        'העתק old/new מדויק מהשורות בקובץ. אל תערוך templates/portal/home.html.\n'
        'סרגל משתמש מחובר: templates/web/base_public.html שורת nav-greeting.\n'
    )

    return ResolvedRequest(
        original_prompt=prompt,
        action=action,
        intent=intent,
        search_terms=terms,
        replace_from=replace_from,
        replace_to=replace_to,
        zones=zones,
        target_files=target_files,
        matched_snippets=matched,
        interpretation_he=interp,
        enriched_prompt=enriched,
    )


def _apply_replace_to_content(
    original: str,
    resolved: ResolvedRequest,
) -> tuple[str, bool]:
    """מחיל החלפה ישירה על תוכן קובץ."""
    modified = original
    changed = False
    old = resolved.replace_from
    new = resolved.replace_to

    # ברכת «יופי» → רק שם משתמש (Django)
    if old == 'יופי' or (
        'יופי' in (old or '') and new and 'user.username' in new
    ):
        patterns = (
            (
                r'(<span\s+class="nav-greeting">)\s*יופי\s*(\{\{\s*user\.username\s*\}\})\s*(</span>)',
                r'\1\2\3',
            ),
            (r'יופי\s+(\{\{\s*user\.username\s*\}\})', r'\1'),
            (r'>יופי\s+(\{\{)', r'>\1'),
        )
        for pat, repl in patterns:
            new_mod = re.sub(pat, repl, modified, count=1, flags=re.IGNORECASE)
            if new_mod != modified:
                modified = new_mod
                changed = True

    if old and new and old in modified:
        modified = modified.replace(old, new, 1)
        changed = True
    elif old and new:
        for line in original.splitlines():
            if old in line:
                modified = modified.replace(line, line.replace(old, new, 1), 1)
                changed = True
                break

    if new and not changed and 'nav-greeting' in modified and 'user.username' in new:
        for line in original.splitlines():
            if 'nav-greeting' in line and 'יופי' in line:
                nl = re.sub(r'\s*יופי\s*', ' ', line, count=1)
                nl = nl.replace('  ', ' ')
                if nl != line:
                    modified = modified.replace(line, nl, 1)
                    changed = True
                break

    return modified, changed


def try_direct_edit(prompt: str, base_dir: Path, resolved: ResolvedRequest) -> str | None:
    """
    עריכה ישירה ללא Gemini כשהבקשה חד-משמעית (הסרה / החלפה).
    מחזיר unified diff או None.
    """
    from .diff_validator import validate_diff_syntax
    from .diff_builder import _unified_diff_for_file

    do_remove = resolved.action == 'remove' and resolved.search_terms
    do_replace = (
        resolved.action == 'replace'
        and (resolved.replace_from or resolved.replace_to)
    ) or (
        resolved.intent in ('replace_text', 'user_page')
        and (resolved.replace_from or 'יופי' in resolved.search_terms)
    )
    if not do_remove and not do_replace:
        return None

    files_to_try = [f for f in resolved.target_files if _should_index(f)][:4]
    if not files_to_try and resolved.matched_snippets:
        files_to_try = list(dict.fromkeys(s.file for s in resolved.matched_snippets))
    if do_replace and 'templates/web/base_public.html' not in files_to_try:
        files_to_try.insert(0, 'templates/web/base_public.html')

    for rel in files_to_try:
        full = base_dir / rel
        if not full.is_file():
            continue
        original = full.read_text(encoding='utf-8', errors='replace')
        modified = original
        changed = False

        if do_replace:
            modified, changed = _apply_replace_to_content(original, resolved)

        if do_remove:
            for term in resolved.search_terms:
                tl = term.lower()
                if tl == 'version':
                    modified = re.sub(
                        r'\s*v\{\{\s*app_version\s*\}\}',
                        '',
                        modified,
                        flags=re.IGNORECASE,
                    )
                    modified = re.sub(
                        r'<meta\s+name="app-version"[^>]*>\s*',
                        '',
                        modified,
                        flags=re.IGNORECASE,
                    )
                    changed = changed or modified != original
                if term in modified:
                    modified = modified.replace(term, '', 1)
                    changed = True
                for line in original.splitlines():
                    if term.lower() in line.lower() and term in line:
                        new_line = line.replace(term, '').replace('  ', ' ')
                        if new_line != line:
                            modified = modified.replace(line, new_line, 1)
                            changed = True

        if changed and modified != original:
            diff = _unified_diff_for_file(rel, original, modified)
            return validate_diff_syntax(diff)
    return None


def select_files_with_index(
    prompt: str,
    base_dir: Path,
    all_files: list[tuple[str, str]] | None = None,
    *,
    max_files: int = 6,
    primary_max_chars: int = 14_000,
    resolved: ResolvedRequest | None = None,
) -> tuple[list[tuple[str, str]], ResolvedRequest]:
    """בחירת קבצים לפי אינדוקס + מילות מפתח (מחליף/מרחיב select_files_for_prompt)."""
    from .diff_builder import select_files_for_prompt

    if resolved is None:
        resolved = resolve_request(prompt, base_dir)

    files = all_files if all_files is not None else list_allowed_files(base_dir)
    if not files:
        return [], resolved

    by_path = {p: c for p, c in files}
    ordered_paths: list[str] = []
    for p in resolved.target_files:
        if p in by_path and p not in ordered_paths:
            ordered_paths.append(p)
    # גיבוי: לוגיקה ישנה
    legacy = select_files_for_prompt(prompt, base_dir, files, max_files=max_files)
    for p, _ in legacy:
        if p not in ordered_paths:
            ordered_paths.append(p)
    for p, _ in files:
        if p not in ordered_paths:
            ordered_paths.append(p)

    out: list[tuple[str, str]] = []
    for i, rel in enumerate(ordered_paths[:max_files]):
        content = by_path.get(rel, '')
        if i == 0 and resolved.target_files and rel in resolved.target_files[:2]:
            content = content[:primary_max_chars]
        else:
            content = content[:4000]
        out.append((rel, content))
    return out, resolved

def format_index_summary(base_dir: Path, max_entries: int = 40) -> str:
    """סיכום אינדוקס לתצוגה בממשק הניהול."""
    index = build_site_index(base_dir)
    lines = ['אינדוקס אתר (תוכן לעריכה בשפה פשוטה):', '']
    by_zone: dict[str, list[TextSnippet]] = {}
    for sn in index:
        by_zone.setdefault(sn.zone_label, []).append(sn)
    for label, items in sorted(by_zone.items()):
        lines.append(f'## {label}')
        for sn in items[:8]:
            t = sn.text[:60] + ('…' if len(sn.text) > 60 else '')
            lines.append(f'  • {t} — {sn.file}:{sn.line}')
        if len(items) > 8:
            lines.append(f'  … ועוד {len(items) - 8}')
        lines.append('')
        if len(lines) > max_entries:
            break
    return '\n'.join(lines[:max_entries])
