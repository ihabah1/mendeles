"""יצירת unified diff באמצעות Gemini API."""
from __future__ import annotations

from pathlib import Path

from django.conf import settings

from .diff_validator import DiffValidationError, normalize_diff_output, validate_diff_syntax
from .path_guard import list_allowed_files


class GeminiServiceError(RuntimeError):
    pass


def _load_system_prompt() -> str:
    path = Path(__file__).resolve().parent.parent / 'prompts' / 'system_prompt.txt'
    return path.read_text(encoding='utf-8')


def _build_user_prompt(request_prompt: str, files: list[tuple[str, str]]) -> str:
    parts = [f'USER REQUEST:\n{request_prompt.strip()}\n']
    parts.append('ALLOWED PROJECT FILES (read-only context):\n')
    for rel, content in files:
        parts.append(f'--- FILE: {rel} ---\n{content}\n')
    parts.append('Respond with unified git diff only.')
    return '\n'.join(parts)


def generate_diff(prompt: str, base_dir: Path | None = None) -> str:
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

    model_name = getattr(settings, 'GEMINI_MODEL', 'gemini-2.0-flash')
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=_load_system_prompt(),
    )

    response = model.generate_content(
        _build_user_prompt(prompt, files),
        generation_config={
            'temperature': 0.1,
            'max_output_tokens': 8192,
        },
    )

    raw = (response.text or '').strip()
    if not raw:
        raise GeminiServiceError('Gemini החזיר תשובה ריקה')
    if 'BLOCKED:' in raw and 'templates/.ai-blocked' in raw:
        raise GeminiServiceError('הבקשה לא ניתנת לביצוע בתיקיות המותרות')

    try:
        normalized = normalize_diff_output(raw)
        return validate_diff_syntax(normalized)
    except DiffValidationError as exc:
        raise GeminiServiceError(str(exc)) from exc
