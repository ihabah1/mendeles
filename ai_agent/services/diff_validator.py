"""אימות unified diff לפני יישום."""
from __future__ import annotations

import re

from .path_guard import validate_diff_paths

MAX_DIFF_BYTES = 512_000
MAX_FILES = 20

DIFF_FILE_HEADER = re.compile(r'^diff --git a/.+ b/.+', re.MULTILINE)
HUNK_HEADER = re.compile(r'^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@', re.MULTILINE)
DIFF_GIT_LINE = re.compile(r'^diff --git a/(.+?) b/(.+?)\s*$', re.MULTILINE)


class DiffValidationError(ValueError):
    pass


def _strip_markdown_fences(text: str) -> str:
    t = text.strip()
    if not t.startswith('```'):
        return t
    lines = t.splitlines()
    if lines and lines[0].startswith('```'):
        lines = lines[1:]
    if lines and lines[-1].strip() == '```':
        lines = lines[:-1]
    return '\n'.join(lines).strip()


def _strip_leading_prose(text: str) -> str:
    """מסיר הסברים לפני/אחרי ה-diff."""
    lines = text.splitlines()
    start = 0
    for i, line in enumerate(lines):
        if line.startswith('diff --git') or line.startswith('--- '):
            start = i
            break
    end = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        if (
            line.startswith('diff --git')
            or line.startswith('--- ')
            or line.startswith('+++ ')
            or line.startswith('@@')
            or line.startswith('+')
            or line.startswith('-')
            or line.startswith(' ')
        ):
            end = i + 1
            break
    return '\n'.join(lines[start:end]).strip()


def _path_from_minus_line(line: str) -> str | None:
    line = line.strip()
    for prefix in ('--- a/', '--- '):
        if line.startswith(prefix):
            path = line[len(prefix):].strip()
            if path == '/dev/null':
                return None
            if '\t' in path:
                path = path.split('\t', 1)[0].strip()
            return path.lstrip('a/').lstrip('b/')
    return None


def _wrap_bare_unified_diff(text: str) -> str:
    """בונה כותרות diff --git כשחסרות."""
    parts = re.split(r'(?=^--- )', text, flags=re.MULTILINE)
    chunks: list[str] = []
    for part in parts:
        part = part.strip()
        if not part.startswith('---'):
            continue
        path = _path_from_minus_line(part.splitlines()[0])
        if not path:
            continue
        header = f'diff --git a/{path} b/{path}'
        if header not in part:
            chunks.append(header)
        chunks.append(part)
    if not chunks:
        raise DiffValidationError('הפלט אינו unified git diff')
    return '\n'.join(chunks).strip() + '\n'


def extract_unified_diff(raw: str) -> str:
    """מחלץ diff מפלט Gemini גם אם יש טקסט מסביב או פורמט חלקי."""
    text = _strip_markdown_fences(raw)
    text = _strip_leading_prose(text)

    if 'diff --git' in text:
        start = text.find('diff --git')
        return text[start:].strip() + '\n'

    if re.search(r'^--- ', text, re.MULTILINE) and re.search(r'^@@ ', text, re.MULTILINE):
        return _wrap_bare_unified_diff(text)

    raise DiffValidationError('הפלט אינו unified git diff')


def normalize_diff_output(raw: str) -> str:
    return extract_unified_diff(raw)


def validate_diff_syntax(diff_text: str) -> str:
    if not diff_text or not diff_text.strip():
        raise DiffValidationError('diff ריק')
    if len(diff_text.encode('utf-8')) > MAX_DIFF_BYTES:
        raise DiffValidationError('ה-diff גדול מדי')

    diff = extract_unified_diff(diff_text) if 'diff --git' not in diff_text else diff_text.strip() + '\n'
    if 'diff --git' not in diff:
        diff = extract_unified_diff(diff_text)

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
    """בדיקות בסיסיות ל-HTML/CSS – לא חוסם שינויי עיצוב קטנים."""
    for line in diff.splitlines():
        if not line.startswith('+') or line.startswith('+++'):
            continue
        payload = line[1:].strip()
        if not payload or payload.startswith('@@'):
            continue
        if '<' in payload and '>' in payload:
            if payload.count('<') > payload.count('>') + 3:
                raise DiffValidationError('ייתכן ש-HTML לא מאוזן בשורה שנוספה')
