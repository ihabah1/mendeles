"""אימות unified diff לפני יישום."""
from __future__ import annotations

import re

from .path_guard import validate_diff_paths

MAX_DIFF_BYTES = 512_000
MAX_FILES = 20

DIFF_FILE_HEADER = re.compile(r'^diff --git a/.+ b/.+', re.MULTILINE)
HUNK_HEADER = re.compile(r'^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@')


class DiffValidationError(ValueError):
    pass


def _strip_markdown_fences(text: str) -> str:
    t = text.strip()
    if t.startswith('```'):
        lines = t.splitlines()
        if lines[0].startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
        t = '\n'.join(lines).strip()
    return t


def normalize_diff_output(raw: str) -> str:
    diff = _strip_markdown_fences(raw)
    if 'diff --git' not in diff:
        raise DiffValidationError('הפלט אינו unified git diff')
    start = diff.find('diff --git')
    return diff[start:].strip() + '\n'


def validate_diff_syntax(diff_text: str) -> str:
    if not diff_text or not diff_text.strip():
        raise DiffValidationError('diff ריק')
    if len(diff_text.encode('utf-8')) > MAX_DIFF_BYTES:
        raise DiffValidationError('ה-diff גדול מדי')

    diff = normalize_diff_output(diff_text)
    file_headers = DIFF_FILE_HEADER.findall(diff)
    if not file_headers:
        raise DiffValidationError('חסרים כותרות diff --git')
    if len(file_headers) > MAX_FILES:
        raise DiffValidationError(f'יותר מ-{MAX_FILES} קבצים ב-diff')

    hunks = HUNK_HEADER.findall(diff)
    if not hunks:
        raise DiffValidationError('חסרים hunks @@')

    dangerous = [
        r'^\+\s*rm\s+-',
        r'^\+\s*sudo\s+',
        r'^\+\s*curl\s+',
        r'^\+\s*wget\s+',
        r'^\+\s*eval\(',
        r'^\+\s*exec\(',
        r'<\?php',
    ]
    for line in diff.splitlines():
        if not line.startswith('+') or line.startswith('+++'):
            continue
        payload = line[1:]
        for pattern in dangerous:
            if re.search(pattern, payload, re.IGNORECASE):
                raise DiffValidationError(f'שורה מסוכנת ב-diff: {line[:120]}')

    validate_diff_paths(diff)
    _validate_template_css_syntax(diff)
    return diff


def _validate_template_css_syntax(diff: str) -> None:
    """בדיקות בסיסיות ל-HTML/CSS בתוך שורות שנוספו."""
    for line in diff.splitlines():
        if not line.startswith('+') or line.startswith('+++'):
            continue
        payload = line[1:].strip()
        if not payload or payload.startswith('@@'):
            continue
        if payload.count('<') != payload.count('>'):
            if '<' in payload and payload.count('<') > payload.count('>') + 2:
                raise DiffValidationError('ייתכן ש-HTML לא מאוזן בשורה שנוספה')
        if payload.count('{') != payload.count('}'):
            if '{' in payload and abs(payload.count('{') - payload.count('}')) > 1:
                raise DiffValidationError('ייתכן ש-CSS לא מאוזן בשורה שנוספה')
