"""מיפוי טקסט גלוי בתבניות ↔ רכיבי UI (לקישור צילומי מסך לקוד)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from .path_guard import list_allowed_files
from .site_index import ResolvedRequest, _should_index

_HEBREW = re.compile(r'[\u0590-\u05FF]{2,}')
_SB_ITEM = re.compile(r'class="sb-item', re.I)
_SB_SECTION = re.compile(r'class="sb-section', re.I)
_NAV_LINK = re.compile(r'class="nav-', re.I)


@dataclass
class UIElement:
    label: str
    file: str
    line: int
    region: str
    element_type: str
    raw_line: str

    @property
    def zone(self) -> str:
        if 'portal/' in self.file.replace('\\', '/'):
            return 'manage'
        return 'public_nav'


def _clean_label(text: str) -> str:
    t = re.sub(r'\s+', ' ', (text or '').strip())
    return t.strip('·|-–—')


def _label_from_line(line: str, element_type: str, region: str) -> str | None:
    if '<script' in line.lower():
        return None
    work = re.sub(r'<span[^>]*class="icon"[^>]*>.*?</span>', ' ', line, flags=re.I | re.DOTALL)
    work = re.sub(r'<[^>]+>', ' ', work)
    work = _clean_label(work)
    if not work or not _HEBREW.search(work):
        return None
    if len(work) > 80:
        return None
    return work


def build_ui_registry(base_dir: Path) -> list[UIElement]:
    """סורק תבניות ומאגד פריטי תפריט/כפתורים עם תווית עברית."""
    elements: list[UIElement] = []
    seen: set[tuple[str, str]] = set()

    for rel, content in list_allowed_files(base_dir):
        if not _should_index(rel):
            continue
        rel_n = rel.replace('\\', '/')
        for i, line in enumerate(content.splitlines(), start=1):
            if _SB_SECTION.search(line):
                sec = _label_from_line(line, 'section', 'sidebar')
                if sec:
                    key = (rel_n, sec)
                    if key not in seen:
                        seen.add(key)
                        elements.append(UIElement(
                            label=sec,
                            file=rel_n,
                            line=i,
                            region='sidebar',
                            element_type='sb-section',
                            raw_line=line.strip()[:220],
                        ))
            region = 'sidebar' if _SB_ITEM.search(line) else 'topbar' if 'topbar-title' in line else 'nav'
            if _SB_ITEM.search(line):
                label = _label_from_line(line, 'nav_link', 'sidebar')
                if label:
                    key = (rel_n, label)
                    if key not in seen:
                        seen.add(key)
                        elements.append(UIElement(
                            label=label,
                            file=rel_n,
                            line=i,
                            region='sidebar',
                            element_type='sb-item',
                            raw_line=line.strip()[:220],
                        ))
            elif _NAV_LINK.search(line) or 'nav-greeting' in line:
                label = _label_from_line(line, 'nav_link', 'nav')
                if label:
                    key = (rel_n, label)
                    if key not in seen:
                        seen.add(key)
                        elements.append(UIElement(
                            label=label,
                            file=rel_n,
                            line=i,
                            region='nav',
                            element_type='nav',
                            raw_line=line.strip()[:220],
                        ))
            elif 'page-title' in line or 'topbar-title' in line:
                label = _label_from_line(line, 'heading', region)
                if label:
                    key = (rel_n, label)
                    if key not in seen:
                        seen.add(key)
                        elements.append(UIElement(
                            label=label,
                            file=rel_n,
                            line=i,
                            region=region,
                            element_type='heading',
                            raw_line=line.strip()[:220],
                        ))

    return elements


def _normalize_label(s: str) -> str:
    return _clean_label(s).lower().replace('״', '"').replace('׳', "'")


def match_labels_to_elements(
    visible_labels: list[str],
    registry: list[UIElement],
) -> list[UIElement]:
    """מקשר טקסט שזוהה בצילום לרכיבים ברשימה."""
    if not visible_labels or not registry:
        return []
    matched: list[UIElement] = []
    used: set[tuple[str, str]] = set()
    norm_registry = [(_normalize_label(e.label), e) for e in registry]

    for raw in visible_labels:
        vis = _normalize_label(raw)
        if len(vis) < 2:
            continue
        for reg_label, el in norm_registry:
            if not reg_label:
                continue
            hit = (
                vis == reg_label
                or vis in reg_label
                or reg_label in vis
                or (len(vis) >= 3 and vis[: max(3, len(vis) - 1)] in reg_label)
            )
            if hit:
                key = (el.file, el.label)
                if key not in used:
                    used.add(key)
                    matched.append(el)
    return matched


def extract_visible_labels_from_images(
    image_paths: list[Path],
    log=None,
) -> list[str]:
    """Gemini Vision – מחזיר תוויות עברית גלויות בצילום."""
    if not image_paths:
        return []
    api_key = getattr(settings, 'GEMINI_API_KEY', '') or ''
    if not api_key:
        return []

    try:
        import google.generativeai as genai
    except ImportError:
        return []

    def _log(msg: str) -> None:
        if log:
            log(msg)

    parts: list = []
    for path in image_paths:
        from .image_attachments import _mime_for_path

        parts.append({'mime_type': _mime_for_path(path), 'data': path.read_bytes()})
    parts.append(
        'This is a screenshot of the Mandeles admin dashboard or public site (Hebrew RTL).\n'
        'List every visible Hebrew UI label: menu items, section titles (e.g. ראשי), '
        'buttons, headings, badges.\n'
        'Return ONLY a JSON array of strings. Example: ["דשבורד","משתמשים","ראשי"]\n'
        'No markdown, no explanation.',
    )

    try:
        genai.configure(api_key=api_key)
        model_name = getattr(settings, 'GEMINI_MODEL', 'gemini-2.5-flash')
        model = genai.GenerativeModel(model_name)
        _log('מנתח צילום מסך – זיהוי טקסט עברי…')
        response = model.generate_content(
            parts,
            generation_config={'temperature': 0.0, 'max_output_tokens': 1024},
        )
        raw = (response.text or '').strip()
        if raw.startswith('```'):
            raw = re.sub(r'^```(?:json)?\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw)
        data = json.loads(raw)
        if isinstance(data, list):
            labels = [_clean_label(str(x)) for x in data if _clean_label(str(x))]
            _log(f'בצילום זוהו: {", ".join(labels[:12])}{"…" if len(labels) > 12 else ""}')
            return labels
    except json.JSONDecodeError:
        _log('לא הצלחנו לפרש JSON מזיהוי צילום – ממשיכים בלי')
    except Exception as exc:
        _log(f'זיהוי צילום: {exc}')
    return []


def apply_vision_to_resolved(
    resolved: ResolvedRequest,
    visible_labels: list[str],
    matched: list[UIElement],
) -> ResolvedRequest:
    """מעשיר את הבקשה אחרי קישור צילום → קוד."""
    if not visible_labels and not matched:
        return resolved

    zones = list(resolved.zones)
    if matched and 'manage' not in zones:
        zones.insert(0, 'manage')
    if any('base_public' in e.file for e in matched) and 'public_nav' not in zones:
        zones.append('public_nav')

    terms = list(resolved.search_terms)
    for lab in visible_labels:
        if lab and lab not in terms:
            terms.append(lab)
    for el in matched:
        if el.label not in terms:
            terms.append(el.label)

    target_files = list(resolved.target_files)
    for el in matched:
        if el.file not in target_files:
            target_files.insert(0, el.file)
    if not target_files and matched:
        target_files = [e.file for e in matched]

    vision_block = ['\n--- VISION / SCREENSHOT (חובה לעקוב) ---']
    vision_block.append(f'טקסט גלוי בצילום: {", ".join(f"«{t}»" for t in visible_labels[:20])}')
    if matched:
        vision_block.append('רכיבים שזוהו בקוד (ערוך את הקבצים האלה):')
        for el in matched[:15]:
            vision_block.append(
                f'- «{el.label}» → {el.file} שורה {el.line} '
                f'({el.element_type}, {el.region})',
            )
            vision_block.append(f'  שורת מקור: {el.raw_line[:160]}')
        vision_block.append(
            'אם המשתמש ביקש לשנות אלמנט שמופיע בצילום – ערוך את השורה המדויקת בקובץ לעיל, '
            'לא קובץ אחר.',
        )
    else:
        vision_block.append(
            'לא נמצאה התאמה מדויקת לרכיבים בתבניות – חפש לפי הטקסט העברי בקבצים המומלצים.',
        )
    if any(e.file.startswith('templates/portal/') for e in matched):
        vision_block.append('אזור: דשבורד ניהול /manage/ → templates/portal/base_dashboard.html + static/css/portal.css')

    enriched = resolved.enriched_prompt + '\n' + '\n'.join(vision_block) + '\n'

    interp = resolved.interpretation_he
    if matched:
        names = ', '.join(f'«{e.label}»' for e in matched[:4])
        interp = f'{interp} · מסך: {names} → {matched[0].file}'

    return ResolvedRequest(
        original_prompt=resolved.original_prompt,
        action=resolved.action,
        intent=resolved.intent,
        search_terms=terms,
        replace_from=resolved.replace_from,
        replace_to=resolved.replace_to,
        zones=zones,
        target_files=target_files,
        matched_snippets=resolved.matched_snippets,
        interpretation_he=interp,
        enriched_prompt=enriched,
    )


def enrich_with_screenshot(
    prompt: str,
    base_dir: Path,
    resolved: ResolvedRequest,
    image_paths: list[Path] | None,
    log=None,
) -> ResolvedRequest:
    """זיהוי צילום + מיפוי לרכיבי UI + עדכון resolved."""
    if not image_paths:
        return resolved
    labels = extract_visible_labels_from_images(image_paths, log=log)
    registry = build_ui_registry(base_dir)
    matched = match_labels_to_elements(labels, registry)
    if log and matched:
        log(
            'קישור צילום→קוד: '
            + ', '.join(f'{e.label}→{e.file}:{e.line}' for e in matched[:5]),
        )
    return apply_vision_to_resolved(resolved, labels, matched)
