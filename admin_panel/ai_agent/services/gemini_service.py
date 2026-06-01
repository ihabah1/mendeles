"""יצירת unified diff באמצעות Gemini API."""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from django.conf import settings

from .diff_builder import generate_diff_via_structured_edits, repair_diff_from_partial_output
from .diff_validator import DiffValidationError, extract_unified_diff, validate_diff_syntax
from .path_guard import list_allowed_files
from .site_index import (
    resolve_request,
    select_files_with_index,
    try_direct_edit,
)
from .ui_registry import enrich_with_screenshot

REPAIR_PROMPT = """
Your previous response was invalid. Output ONLY a unified git diff.
Start with: diff --git a/FILENAME b/FILENAME
Then --- a/FILENAME
Then +++ b/FILENAME
Then @@ -LINE,COUNT +LINE,COUNT @@
Then lines starting with space (context), minus (removed), or plus (added).

Example:
diff --git a/static/css/portal.css b/static/css/portal.css
--- a/static/css/portal.css
+++ b/static/css/portal.css
@@ -28,7 +28,7 @@
 .page-sub{font-size:.75rem;color:var(--muted);margin-top:2px}
-.page-title{font-size:1.1rem;font-weight:700}
+.page-title{font-size:1.4rem;font-weight:700}
 .stats-grid{display:grid;
"""


class GeminiServiceError(RuntimeError):
    pass


def _load_system_prompt() -> str:
    path = Path(__file__).resolve().parent.parent / 'prompts' / 'system_prompt.txt'
    return path.read_text(encoding='utf-8')


def _build_user_prompt(
    request_prompt: str,
    files: list[tuple[str, str]],
    *,
    index_context: str = '',
    image_paths: list[Path] | None = None,
) -> str:
    parts = []
    if index_context.strip():
        parts.append(index_context.strip())
        parts.append('')
    if image_paths:
        parts.append(
            'REFERENCE IMAGES: Screenshot(s) of the live UI.\n'
            'If a VISION / SCREENSHOT block lists mapped elements (Hebrew label → file:line), '
            'you MUST edit those exact files/lines for the element the user points at.\n'
            'Example: «דשבורד» in sidebar → templates/portal/base_dashboard.html sb-item line.\n',
        )
    parts.append(f'USER REQUEST:\n{request_prompt.strip()}\n')
    parts.append('ALLOWED PROJECT FILES (read-only context):\n')
    for rel, content in files[:10]:
        parts.append(f'--- FILE: {rel} ---\n{content}\n')
    if len(files) > 10:
        parts.append(f'... and {len(files) - 10} more files')
    parts.append(
        '\nOUTPUT: unified git diff only. Must include @@ -N,M +N,M @@ hunk headers.\n',
    )
    return '\n'.join(parts)


def _parse_gemini_response(raw: str, root: Path, log: Callable[[str], None]) -> str:
    if not raw.strip():
        raise GeminiServiceError('Gemini החזיר תשובה ריקה')
    if 'BLOCKED:' in raw and '.ai-blocked' in raw:
        raise GeminiServiceError('הבקשה לא ניתנת לביצוע בתיקיות המותרות')

    try:
        extracted = extract_unified_diff(raw)
        return validate_diff_syntax(extracted)
    except DiffValidationError as first_err:
        log(f'ניסיון תיקון פורמט: {first_err}')
        if 'hunk' in str(first_err).lower() or 'diff --git' in raw or '--- ' in raw:
            try:
                log('בונה diff מקומית מפלט חלקי…')
                return repair_diff_from_partial_output(raw, root)
            except DiffValidationError as repair_err:
                log(f'תיקון מקומי: {repair_err}')
        raise first_err


def _call_gemini(
    model,
    user_prompt: str,
    image_paths: list[Path] | None = None,
) -> str:
    generation_config = {
        'temperature': 0.0,
        'max_output_tokens': 8192,
    }
    if image_paths:
        parts: list = []
        for path in image_paths:
            from .image_attachments import _mime_for_path

            parts.append({
                'mime_type': _mime_for_path(path),
                'data': path.read_bytes(),
            })
        parts.append(user_prompt)
        response = model.generate_content(
            parts,
            generation_config=generation_config,
        )
    else:
        response = model.generate_content(
            user_prompt,
            generation_config=generation_config,
        )
    return (response.text or '').strip()


def generate_diff(
    prompt: str,
    base_dir: Path | None = None,
    log_callback: Callable[[str], None] | None = None,
    image_paths: list[Path] | None = None,
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
    if getattr(settings, 'GITHUB_TOKEN', ''):
        try:
            from admin_panel.ai_agent.git_tools.repo import ensure_github_context_clone

            root = ensure_github_context_clone()
            log('קורא קבצים מ-GitHub (origin/main) ליצירת diff מדויק…')
        except Exception as exc:
            log(f'GitHub clone לקונטקסט: {exc} – משתמש בקבצי השרת')
    all_files = list_allowed_files(root)
    if not all_files:
        raise GeminiServiceError('לא נמצאו קבצים מותרים בפרויקט')

    from .new_page import build_new_page_diff, is_new_page_request

    if is_new_page_request(prompt):
        log('זוהתה בקשה ליצירת דף חדש – בונה קובץ template חדש (לא עורך קבצים קיימים)…')
        return build_new_page_diff(
            prompt, root, log_callback=log, image_paths=image_paths,
        )

    resolved = resolve_request(prompt, root)
    if image_paths:
        log(f'מצורפות {len(image_paths)} תמונות – מקשר צילום לרכיבים בקוד…')
        resolved = enrich_with_screenshot(prompt, root, resolved, image_paths, log=log)

    log(f'פרשנות: {resolved.to_log_line()}')
    if resolved.search_terms:
        log(f'מונחי חיפוש: {", ".join(resolved.search_terms[:8])}')
    if resolved.target_files:
        log(f'קבצים מומלצים: {", ".join(resolved.target_files[:4])}')

    direct = try_direct_edit(prompt, root, resolved)
    if direct:
        log('שינוי ישיר מהאינדוקס (ללא Gemini)')
        return direct

    files, resolved = select_files_with_index(
        prompt, root, all_files, max_files=10, resolved=resolved,
    )
    log(f'נקראו {len(all_files)} קבצים, {len(files)} רלוונטיים לבקשה')
    model_name = getattr(settings, 'GEMINI_MODEL', 'gemini-2.5-flash')
    log(f'שולח בקשה ל-Gemini ({model_name})…')
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=_load_system_prompt(),
    )

    user_prompt = _build_user_prompt(
        prompt,
        files,
        index_context=resolved.enriched_prompt,
        image_paths=image_paths,
    )
    raw = _call_gemini(model, user_prompt, image_paths=image_paths)
    log('תשובה התקבלה מ-Gemini – מעבד diff…')

    last_error: Exception | None = None
    for attempt, extra in enumerate(('', REPAIR_PROMPT), start=1):
        try:
            if attempt > 1:
                log('ניסיון שני ל-Gemini (תיקון פורמט)…')
                raw = _call_gemini(
                    model,
                    user_prompt + '\n\n' + extra + f'\n\nPrevious output:\n{raw[:3000]}',
                    image_paths=image_paths,
                )
                log('תשובה שנייה התקבלה – מעבד diff…')
            return _parse_gemini_response(raw, root, log)
        except (DiffValidationError, GeminiServiceError) as exc:
            last_error = exc
            if attempt >= 2:
                break

    log('מנסה גיבוי JSON + בניית diff בשרת…')
    try:
        return generate_diff_via_structured_edits(prompt, root, log_callback=log)
    except (DiffValidationError, json.JSONDecodeError, ValueError) as exc:
        detail = str(exc).strip()
        hint = (
            'לא הצלחנו לייצר diff. נסח בשפה פשוטה, למשל: '
            '«במקום המילה יופי שיופיע שם משתמש», '
            '«תוריד את המילה version מהדף הראשי», '
            '«הוסף דף שמציג /api/stats». '
            'אפשר גם לציין נתיב: templates/web/base_public.html'
        )
        if detail and detail not in hint:
            hint = f'{hint} ({detail})'
        raise GeminiServiceError(hint) from (last_error or exc)
