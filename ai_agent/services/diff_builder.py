"""בניית unified diff מקומית (גיבוי כש-Gemini לא מחזיר פורמט מלא)."""
from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

from django.conf import settings

from .diff_validator import DiffValidationError, validate_diff_syntax
from .path_guard import is_path_allowed, list_allowed_files


def _unified_diff_for_file(rel_path: str, old_text: str, new_text: str) -> str:
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    if not old_lines and not new_lines:
        return ''
    if old_lines and not old_lines[-1].endswith('\n'):
        old_lines[-1] += '\n'
    if new_lines and not new_lines[-1].endswith('\n'):
        new_lines[-1] += '\n'
    lines = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f'a/{rel_path}',
        tofile=f'b/{rel_path}',
        lineterm='',
    )
    body = '\n'.join(lines)
    if not body.endswith('\n'):
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
    text = raw.strip()
    if '```' in text:
        m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if m:
            text = m.group(1)
        else:
            start = text.find('{')
            end = text.rfind('}')
            if start >= 0 and end > start:
                text = text[start : end + 1]
    return json.loads(text)


def generate_diff_via_structured_edits(
    prompt: str,
    base_dir: Path,
    log_callback=None,
) -> str:
    """גיבוי: Gemini מחזיר JSON עם old/new והשרת בונה diff."""
    import google.generativeai as genai

    def log(msg: str):
        if log_callback:
            log_callback(msg)

    api_key = getattr(settings, 'GEMINI_API_KEY', '') or ''
    model_name = getattr(settings, 'GEMINI_MODEL', 'gemini-2.5-flash')
    genai.configure(api_key=api_key)

    files = list_allowed_files(base_dir)[:8]
    context = '\n'.join(f'FILE {p}:\n{c[:4000]}\n' for p, c in files)

    system = (
        'Return ONLY valid JSON, no markdown. Schema: '
        '{"edits":[{"file":"path/under/templates/or/static","old":"exact text from file",'
        '"new":"replacement text"}]} '
        'Use exact substrings from file for "old". One or two small edits only.'
    )
    model = genai.GenerativeModel(model_name=model_name, system_instruction=system)
    user = f'REQUEST:\n{prompt}\n\nFILES:\n{context}'

    log('גיבוי: מבקש שינויים בפורמט JSON…')
    response = model.generate_content(
        user,
        generation_config={'temperature': 0.0, 'max_output_tokens': 4096},
    )
    raw = (response.text or '').strip()
    data = _extract_json(raw)
    edits = data.get('edits') or []
    if not edits:
        raise DiffValidationError('אין edits ב-JSON')

    parts: list[str] = []
    for edit in edits:
        rel = (edit.get('file') or '').strip().lstrip('./')
        old = edit.get('old') or ''
        new = edit.get('new') or ''
        if not rel or old == '':
            continue
        ok, reason = is_path_allowed(rel)
        if not ok:
            raise DiffValidationError(reason)
        full = base_dir / rel
        if not full.is_file():
            raise DiffValidationError(f'קובץ לא קיים: {rel}')
        original = full.read_text(encoding='utf-8', errors='replace')
        if old not in original:
            raise DiffValidationError(f'הטקסט לחיפוש לא נמצא ב-{rel}')
        modified = original.replace(old, new, 1)
        if original == modified:
            raise DiffValidationError(f'אין שינוי ב-{rel}')
        log(f'בניית diff מקומית ל-{rel}')
        parts.append(_unified_diff_for_file(rel, original, modified))

    if not parts:
        raise DiffValidationError('לא נוצרו שינויים')
    combined = '\n'.join(parts)
    return validate_diff_syntax(combined)
