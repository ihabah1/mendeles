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
            'templates/web/home.html',
            'templates/web/partials/lotto_panel.html',
            'templates/web/base_public.html',
            'static/css/public_site.css',
        ),
    },
    'public_nav': {
        'label': 'סרגל עליון / תפריט',
        'keywords': (
            'סרגל', 'תפריט', 'ניווט', 'למעלה', 'header', 'nav', 'לוגו', 'logo',
            'version', 'גרסה', 'v2', 'מצב הדגמה', 'הדגמה', 'demo',
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
_QUOTED = re.compile(r'["\'«»]([^"\'«»]+)["\'«»]')
_THE_WORD = re.compile(
    r'(?:את\s+)?(?:המילה|הטקסט|הכיתוב|המשפט|מילה)?\s*["\']?([^"\']+?)["\']?\s+'
    r'(?:מה|מ|ב|בתוך|בתחתית|בסרגל|בדף)',
    re.IGNORECASE,
)
_STRIP_TAGS = re.compile(r'<[^>]+>')
_DJANGO_VAR = re.compile(r'\{\{[^}]+\}\}|\{%[^%]+%\}')

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
    search_terms: list[str] = field(default_factory=list)
    zones: list[str] = field(default_factory=list)
    target_files: list[str] = field(default_factory=list)
    matched_snippets: list[TextSnippet] = field(default_factory=list)
    interpretation_he: str = ''
    enriched_prompt: str = ''

    def to_log_line(self) -> str:
        return self.interpretation_he or 'לא זוהתה כוונה מדויקת'


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
    if _ACTION_REPLACE.search(prompt):
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
    zones = _detect_zones(prompt_l)
    terms = _extract_search_terms(prompt, prompt_l)

    index = build_site_index(base_dir)
    matched = _match_snippets(index, zones, terms)
    target_files = _rank_files(zones, matched, terms)

    zone_labels = ', '.join(ZONES[z]['label'] for z in zones[:3])
    term_str = ', '.join(f'«{t}»' for t in terms[:4]) if terms else '—'

    if action == 'remove':
        interp = f'הסרת תוכן ({term_str}) מ{zone_labels}'
    elif action == 'replace':
        interp = f'החלפת תוכן ({term_str}) ב{zone_labels}'
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
    enriched += (
        '\nהוראה: בצע את השינוי בקבצים המומלצים בלבד. '
        'העתק old/new מדויק מהשורות בקובץ. אל תערוך templates/portal/home.html.\n'
    )

    return ResolvedRequest(
        original_prompt=prompt,
        action=action,
        search_terms=terms,
        zones=zones,
        target_files=target_files,
        matched_snippets=matched,
        interpretation_he=interp,
        enriched_prompt=enriched,
    )


def try_direct_edit(prompt: str, base_dir: Path, resolved: ResolvedRequest) -> str | None:
    """
    עריכה ישירה ללא Gemini כשהבקשה חד-משמעית (הסרת מחרוזת).
    מחזיר unified diff או None.
    """
    from .diff_validator import validate_diff_syntax
    from .diff_builder import _unified_diff_for_file

    if resolved.action != 'remove' or not resolved.search_terms:
        return None

    files_to_try = [f for f in resolved.target_files if _should_index(f)][:4]
    if not files_to_try and resolved.matched_snippets:
        files_to_try = list(dict.fromkeys(s.file for s in resolved.matched_snippets))

    for rel in files_to_try:
        full = base_dir / rel
        if not full.is_file():
            continue
        original = full.read_text(encoding='utf-8', errors='replace')
        modified = original
        changed = False

        for term in resolved.search_terms:
            tl = term.lower()
            if tl == 'version':
                # הסרת תצוגת גרסה בסרגל
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
                if modified != original:
                    changed = True
            if term in modified:
                modified = modified.replace(term, '', 1)
                changed = True
            # גרסה עם רווחים סביב
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
