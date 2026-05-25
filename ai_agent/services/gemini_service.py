"""יצירת unified diff באמצעות Gemini API."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from django.conf import settings

from .diff_validator import DiffValidationError, extract_unified_diff, validate_diff_syntax
from .path_guard import list_allowed_files

REPAIR_PROMPT = """
Your previous response was NOT a valid unified git diff.
Reply again with ONLY a unified git diff. Start with the line: diff --git
No markdown. No explanation. Use this exact structure:

diff --git a/static/css/portal.css b/static/css/portal.css
--- a/static/css/portal.css
+++ b/static/css/portal.css
@@ -1,1 +1,1 @@
-old value
+new value
"""


class GeminiServiceError(RuntimeError):
    pass


def _load_system_prompt() -> str:
    path = Path(__file__).resolve().parent.parent / 'prompts' / 'system_prompt.txt'
    return path.read_text(encoding='utf-8')


def _build_user_prompt(request_prompt: str, files: list[tuple[str, str]]) -> str:
    parts = [f'USER REQUEST:\n{request_prompt.strip()}\n']
    parts.append('ALLOWED PROJECT FILES (read-only context):\n')
    for rel, content in files[:12]:
        parts.append(f'--- FILE: {rel} ---\n{content}\n')
    if len(files) > 12:
        parts.append(f'... and {len(files) - 12} more files')
    parts.append(
        '\nOUTPUT: unified git diff only. First line must be: diff --git a/... b/...\n',
    )
    return '\n'.join(parts)


def _parse_gemini_response(raw: str, log: Callable[[str], None]) -> str:
    if not raw.strip():
        raise GeminiServiceError('Gemini החזיר תשובה ריקה')
    if 'BLOCKED:' in raw and '.ai-blocked' in raw:
        raise GeminiServiceError('הבקשה לא ניתנת לביצוע בתיקיות המותרות')

    try:
        extracted = extract_unified_diff(raw)
        return validate_diff_syntax(extracted)
    except DiffValidationError as first_err:
        log(f'ניסיון תיקון פורמט: {first_err}')
        try:
            if '--- ' in raw and '@@' in raw:
                wrapped = extract_unified_diff(raw)
                return validate_diff_syntax(wrapped)
        except DiffValidationError:
            pass
        raise first_err


def _call_gemini(model, user_prompt: str) -> str:
    response = model.generate_content(
        user_prompt,
        generation_config={
            'temperature': 0.0,
            'max_output_tokens': 8192,
        },
    )
    return (response.text or '').strip()


def generate_diff(
    prompt: str,
    base_dir: Path | None = None,
    log_callback: Callable[[str], None] | None = None,
) -> str:
    def log(msg: str):
        if log_callback:
            log_callback(msg)

    api_key = getattr(settings, 'GEMINI_API_KEY', '') or ''
    if not api_key:
        raise GeminiServiceError('GEMINI_API_KEY לא מוגדר')

    try:
        import google.generativeai as genai
    except ImportError as exc:
        raise GeminiServiceError('חבילת google-generativeai לא מותקנת') from exc

    root = base_dir or settings.BASE_DIR
    files = list_allowed_files(root)
    if not files:
        raise GeminiServiceError('לא נמצאו קבצים מותרים בפרויקט')

    log(f'נקראו {len(files)} קבצים לקונטקסט')
    model_name = getattr(settings, 'GEMINI_MODEL', 'gemini-2.5-flash')
    log(f'שולח בקשה ל-Gemini ({model_name})…')
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=_load_system_prompt(),
    )

    user_prompt = _build_user_prompt(prompt, files)
    raw = _call_gemini(model, user_prompt)
    log('תשובה התקבלה מ-Gemini – מעבד diff…')

    try:
        return _parse_gemini_response(raw, log)
    except DiffValidationError:
        log('ניסיון שני ל-Gemini (תיקון פורמט)…')
        raw2 = _call_gemini(
            model,
            user_prompt + '\n\n' + REPAIR_PROMPT + f'\n\nPrevious bad output:\n{raw[:2000]}',
        )
        log('תשובה שנייה התקבלה – מעבד diff…')
        try:
            return _parse_gemini_response(raw2, log)
        except DiffValidationError as exc:
            raise GeminiServiceError(
                'Gemini לא החזיר diff תקין. נסח מחדש את הבקשה (למשל: שנה ב-static/css/portal.css את …)',
            ) from exc
