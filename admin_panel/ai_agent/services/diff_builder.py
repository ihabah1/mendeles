"""בניית unified diff מקומית (גיבוי כש-Gemini לא מחזיר פורמט מלא)."""
from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

from django.conf import settings

from .diff_validator import DiffValidationError, validate_diff_syntax
from .path_guard import is_path_allowed, list_allowed_files

_PATH_IN_PROMPT = re.compile(
    r'((?:static|templates)/[\w./-]+\.(?:css|html|js|txt|svg))',
    re.IGNORECASE,
)


def select_files_for_prompt(
    prompt: str,
    base_dir: Path,
    all_files: list[tuple[str, str]] | None = None,
    *,
    max_files: int = 6,
    primary_max_chars: int = 14_000,
) -> list[tuple[str, str]]:
    """בוחר קבצים רלוונטיים לבקשה (נתיב מפורש בפרומפט קודם)."""
    files = all_files if all_files is not None else list_allowed_files(base_dir)
    if not files:
        return []

    prompt_l = prompt.lower()
    explicit = [m.group(1).replace('\\', '/') for m in _PATH_IN_PROMPT.finditer(prompt)]
    # מילות מפתח → קבצי אתר ראשי (Django)
    if any(
        k in prompt_l
        for k in (
            'דף ראשי',
            'דף הבית',
            'אתר ראשי',
            'סרגל',
            'ניווט',
            'מצב הדגמה',
            'לוטו',
            'טוטו',
            'רכוש גישה',
            'אסטרטגיית',
            'יופי',
            'שם משתמש',
            'nav-greeting',
            'דף חדש',
            'api',
        )
    ):
        explicit.extend([
            'templates/web/base_public.html',
            'templates/web/home.html',
            'templates/web/partials/lotto_panel.html',
            'static/css/public_site.css',
        ])
    by_name: list[tuple[str, str]] = []
    rest: list[tuple[str, str]] = []

    for rel, content in files:
        rl = rel.lower()
        hit = (
            rl in prompt_l
            or rl.split('/')[-1] in prompt_l
            or any(rl == e.lower() or rl.endswith(e.lower()) for e in explicit)
        )
        if hit:
            by_name.append((rel, content))
        else:
            rest.append((rel, content))

    ordered = by_name + rest
    out: list[tuple[str, str]] = []
    for i, (rel, content) in enumerate(ordered[:max_files]):
        if i == 0 and by_name:
            content = content[:primary_max_chars]
        else:
            content = content[:4000]
        out.append((rel, content))
    return out


def _unified_diff_for_file(rel_path: str, old_text: str, new_text: str) -> str:
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    if not old_lines and not new_lines:
        return ''
    if old_lines and not old_lines[-1].endswith('\n'):
        old_lines[-1] += '\n'
    if new_lines and not new_lines[-1].endswith('\n'):
        new_lines[-1] += '\n'
    body = ''.join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f'a/{rel_path}',
            tofile=f'b/{rel_path}',
            lineterm='\n',
        )
    )
    if body and not body.endswith('\n'):
        body += '\n'
    return f'diff --git a/{rel_path} b/{rel_path}\n{body}'


def apply_line_edits_to_content(content: str, diff_body: str) -> str:
    """מיישם שורות - / + על תוכן הקובץ."""
    result = content
    lines = diff_body.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('---') or line.startswith('+++') or line.startswith('@@'):
            i += 1
            continue
        if line.startswith('-') and not line.startswith('---'):
            old = line[1:]
            new = ''
            if i + 1 < len(lines) and lines[i + 1].startswith('+') and not lines[i + 1].startswith('+++'):
                new = lines[i + 1][1:]
                i += 2
            else:
                i += 1
            if old and old not in result:
                raise DiffValidationError(f'השורה להסרה לא נמצאה בקובץ: {old[:100]}')
            if old:
                result = result.replace(old, new, 1)
            continue
        if line.startswith('+') and not line.startswith('+++'):
            insert = line[1:]
            result = result + ('\n' if result and not result.endswith('\n') else '') + insert
            i += 1
            continue
        i += 1
    return result


def repair_diff_from_partial_output(raw: str, base_dir: Path) -> str:
    """בונה diff תקין מפלט חלקי (---/+++/-/+ בלי @@)."""
    text = raw.strip()
    sections = re.split(r'(?=^--- )', text, flags=re.MULTILINE)
    parts: list[str] = []

    for section in sections:
        section = section.strip()
        if not section.startswith('---'):
            continue
        header_line = section.splitlines()[0]
        path = header_line.replace('---', '').strip()
        for prefix in ('a/', 'b/'):
            if path.startswith(prefix):
                path = path[len(prefix):]
        if '\t' in path:
            path = path.split('\t', 1)[0].strip()
        ok, reason = is_path_allowed(path)
        if not ok:
            raise DiffValidationError(reason)

        full = base_dir / path
        if not full.is_file():
            raise DiffValidationError(f'קובץ לא קיים: {path}')
        original = full.read_text(encoding='utf-8', errors='replace')
        modified = apply_line_edits_to_content(original, section)
        if original == modified:
            raise DiffValidationError(f'לא זוהה שינוי בקובץ {path}')
        parts.append(_unified_diff_for_file(path, original, modified))

    if not parts:
        raise DiffValidationError('לא ניתן לבנות diff מהפלט')
    combined = '\n'.join(parts)
    return validate_diff_syntax(combined)


def _extract_json(raw: str) -> dict:
    text = (raw or '').strip()
    if not text:
        raise DiffValidationError('Gemini החזיר JSON ריק')

    fence = re.search(r'```(?:json)?\s*(\{.*\})\s*```', text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        start = text.find('{')
        end = text.rfind('}')
        if start >= 0 and end > start:
            text = text[start : end + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise DiffValidationError(f'JSON לא תקין: {exc}') from exc


def _normalize_edits(data: dict) -> list[dict]:
    if not isinstance(data, dict):
        return []
    edits = data.get('edits') or data.get('changes') or data.get('files') or []
    if isinstance(data.get('edit'), dict):
        edits = [data['edit']]
    if isinstance(edits, dict):
        edits = [edits]
    return [e for e in edits if isinstance(e, dict)]


def _apply_edits_list(edits: list[dict], base_dir: Path, log) -> list[str]:
    parts: list[str] = []
    for edit in edits:
        rel = (edit.get('file') or edit.get('path') or '').strip().lstrip('./')
        old = edit.get('old') if edit.get('old') is not None else edit.get('from', '')
        new = edit.get('new') if edit.get('new') is not None else edit.get('to', '')
        old = str(old)
        new = str(new)
        if not rel:
            continue
        ok, reason = is_path_allowed(rel)
        if not ok:
            raise DiffValidationError(reason)
        full = base_dir / rel
        if not full.is_file():
            raise DiffValidationError(f'קובץ לא קיים: {rel}')
        original = full.read_text(encoding='utf-8', errors='replace')
        if not old.strip():
            raise DiffValidationError(f'חסר טקסט old ב-{rel}')
        if old not in original:
            raise DiffValidationError(
                f'הטקסט לחיפוש לא נמצא ב-{rel}. ודא שהבקשה תואמת לקובץ ב-GitHub.',
            )
        modified = original.replace(old, new, 1)
        if original == modified:
            raise DiffValidationError(f'אין שינוי ב-{rel}')
        log(f'בניית diff מקומית ל-{rel}')
        parts.append(_unified_diff_for_file(rel, original, modified))
    return parts


def _call_json_model(prompt: str, files: list[tuple[str, str]], *, focused: bool = False):
    import google.generativeai as genai

    api_key = getattr(settings, 'GEMINI_API_KEY', '') or ''
    model_name = getattr(settings, 'GEMINI_MODEL', 'gemini-2.5-flash')
    genai.configure(api_key=api_key)

    example = (
        '{"edits":[{"file":"static/css/portal.css",'
        '"old":".page-title{font-size:1.1rem;font-weight:700}",'
        '"new":".page-title{font-size:1.4rem;font-weight:700}"}]}'
    )
    system = (
        'You output ONLY valid JSON. No markdown, no explanation. '
        f'Schema exactly: {example} '
        'Rules: "old" must be copied EXACTLY from the file content below (one line or contiguous substring). '
        'At least one edit. Only paths under static/ or templates/.'
    )
    if focused and files:
        system += f' Edit ONLY file: {files[0][0]}'

    model = genai.GenerativeModel(model_name=model_name, system_instruction=system)
    context = '\n\n'.join(f'=== {p} ===\n{c}' for p, c in files)
    user = f'USER REQUEST:\n{prompt}\n\nFILE CONTENTS:\n{context}'

    try:
        import google.generativeai as genai

        gen_cfg = genai.GenerationConfig(
            temperature=0.0,
            max_output_tokens=8192,
            response_mime_type='application/json',
        )
    except Exception:
        gen_cfg = {'temperature': 0.0, 'max_output_tokens': 8192}

    response = model.generate_content(user, generation_config=gen_cfg)
    return (response.text or '').strip()


def generate_diff_via_structured_edits(
    prompt: str,
    base_dir: Path,
    log_callback=None,
) -> str:
    """גיבוי: Gemini מחזיר JSON עם old/new והשרת בונה diff."""

    def log(msg: str):
        if log_callback:
            log_callback(msg)

    all_files = list_allowed_files(base_dir)
    if not all_files:
        raise DiffValidationError('לא נמצאו קבצים לעיבוד')

    from .site_index import resolve_request, select_files_with_index, try_direct_edit

    resolved = resolve_request(prompt, base_dir)
    log(f'פרשנות (גיבוי): {resolved.to_log_line()}')
    direct = try_direct_edit(prompt, base_dir, resolved)
    if direct:
        log('שינוי ישיר מהאינדוקס')
        return direct

    files, resolved = select_files_with_index(
        prompt, base_dir, all_files, resolved=resolved,
    )
    prompt_for_model = resolved.enriched_prompt or prompt
    if files:
        log(f'קבצים לגיבוי JSON: {", ".join(p for p, _ in files[:4])}')

    last_err: DiffValidationError | None = None
    for attempt, focused in enumerate((False, True), start=1):
        try:
            if attempt > 1 and files:
                log('גיבוי JSON: ניסיון שני על קובץ ממוקד…')
            else:
                log('גיבוי: מבקש שינויים בפורמט JSON…')
            raw = _call_json_model(prompt_for_model, files, focused=focused)
            if not raw:
                raise DiffValidationError('תשובת JSON ריקה')
            data = _extract_json(raw)
            edits = _normalize_edits(data)
            if not edits:
                preview = raw[:280].replace('\n', ' ')
                raise DiffValidationError(f'אין edits ב-JSON. תשובה: {preview}…')
            parts = _apply_edits_list(edits, base_dir, log)
            if not parts:
                raise DiffValidationError('לא נוצרו שינויים מה-edits')
            combined = '\n'.join(parts)
            return validate_diff_syntax(combined)
        except DiffValidationError as exc:
            last_err = exc
            if attempt >= 2 or not files:
                break

    explicit = [m.group(1) for m in _PATH_IN_PROMPT.finditer(prompt)]
    hint = (
        'ציין נתיב מלא מהרשימה, למשל: '
        'ב-static/css/portal.css שנה את .page-title ל-font-size: 1.4rem'
    )
    if explicit:
        hint = f'ב-{explicit[0]} …'
    raise DiffValidationError(f'{last_err}. {hint}') from last_err
