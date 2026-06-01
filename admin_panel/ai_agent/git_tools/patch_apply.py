"""יישום unified diff ב-Python כש-git apply נכשל (קונטקסט לא תואם)."""
from __future__ import annotations

import re
from pathlib import Path

from admin_panel.ai_agent.services.path_guard import extract_paths_from_diff, normalize_repo_path, validate_diff_paths

DIFF_SPLIT = re.compile(r'^diff --git ', re.MULTILINE)
HUNK_START = re.compile(r'^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@')


def _path_from_diff_header(line: str) -> str | None:
    for prefix in ('--- a/', '--- '):
        if line.startswith(prefix):
            p = line[len(prefix):].strip()
            if p == '/dev/null':
                return None
            if '\t' in p:
                p = p.split('\t', 1)[0]
            return normalize_repo_path(p)
    return None


def _hunk_old_new(hunk_lines: list[str]) -> tuple[list[str], list[str]]:
    old: list[str] = []
    new: list[str] = []
    for line in hunk_lines:
        if not line:
            old.append('')
            new.append('')
        elif line[0] == ' ':
            old.append(line[1:])
            new.append(line[1:])
        elif line[0] == '-':
            old.append(line[1:])
        elif line[0] == '+':
            new.append(line[1:])
    return old, new


def _find_block(lines: list[str], block: list[str], start: int = 0) -> int:
    if not block:
        return start
    n, m = len(lines), len(block)
    for i in range(start, n - m + 1):
        if lines[i : i + m] == block:
            return i
    return -1


def _apply_hunk_to_lines(file_lines: list[str], hunk_lines: list[str]) -> list[str]:
    old, new = _hunk_old_new(hunk_lines)
    if not old and not new:
        return file_lines

    pos = _find_block(file_lines, old)
    if pos < 0 and old:
        # נסה רק שורות שהוסרו (ללא context של +)
        removed = [ln for ln in hunk_lines if ln.startswith('-') and not ln.startswith('---')]
        removed_text = [ln[1:] for ln in removed]
        if removed_text:
            pos = _find_block(file_lines, removed_text)
            if pos >= 0:
                old = removed_text
                new = _hunk_old_new(
                    [ln for ln in hunk_lines if not (ln.startswith('-') and not ln.startswith('---'))]
                )[1]
                if len(new) < len(old):
                    new = new + [''] * (len(old) - len(new))

    if pos < 0:
        raise ValueError('לא נמצא קונטקסט בקובץ להחלת hunk')

    return file_lines[:pos] + new + file_lines[pos + len(old) :]


def _apply_replacements(content: str, section: str) -> str:
    """גיבוי: זוגות - / + רצופים כ-replace."""
    lines = section.splitlines()
    result = content
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('-') and not line.startswith('---'):
            old = line[1:]
            new = ''
            if i + 1 < len(lines) and lines[i + 1].startswith('+') and not lines[i + 1].startswith('+++'):
                new = lines[i + 1][1:]
                i += 2
            else:
                i += 1
            if old and old in result:
                result = result.replace(old, new, 1)
            continue
        i += 1
    return result


def apply_unified_diff_to_repo(repo: Path, diff_text: str) -> list[str]:
    validate_diff_paths(diff_text)
    paths = extract_paths_from_diff(diff_text)
    touched: list[str] = []

    parts = DIFF_SPLIT.split(diff_text)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if not part.startswith('diff --git'):
            part = 'diff --git ' + part
        lines = part.splitlines()
        # זיהוי קובץ חדש: "--- /dev/null" או "new file mode"
        is_new = ('--- /dev/null' in part) or bool(re.search(r'^new file mode', part, re.MULTILINE))
        rel = None
        plus_target = None
        for line in lines[:8]:
            if line.startswith('--- '):
                r = _path_from_diff_header(line)
                if r:
                    rel = r
            elif line.startswith('+++ '):
                t = line[4:].strip()
                if t and t != '/dev/null':
                    if '\t' in t:
                        t = t.split('\t', 1)[0]
                    plus_target = normalize_repo_path(t)
        if rel is None and plus_target is not None:
            rel = plus_target
            is_new = True
        if not rel:
            continue

        full = repo / rel
        if is_new:
            # יצירת קובץ חדש מתוך שורות ה-+ (דף חדש בניהול שינויים)
            added = [ln[1:] for ln in lines if ln.startswith('+') and not ln.startswith('+++')]
            new_content = '\n'.join(added)
            if not new_content.endswith('\n'):
                new_content += '\n'
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(new_content, encoding='utf-8', newline='\n')
            touched.append(rel)
            continue
        if not full.is_file():
            raise ValueError(f'קובץ לא קיים ב-clone: {rel}')

        content = full.read_text(encoding='utf-8', errors='replace')
        file_lines = content.splitlines()
        had_nl = content.endswith('\n')

        hunks: list[list[str]] = []
        current: list[str] = []
        in_hunk = False
        for line in lines:
            if HUNK_START.match(line):
                if current:
                    hunks.append(current)
                current = []
                in_hunk = True
                continue
            if in_hunk:
                if line.startswith('diff --git') or line.startswith('--- ') or line.startswith('+++'):
                    in_hunk = False
                    if current:
                        hunks.append(current)
                        current = []
                    continue
                if line.startswith((' ', '-', '+')):
                    current.append(line)
        if current:
            hunks.append(current)

        modified_lines = file_lines
        applied = 0
        for hunk in hunks:
            try:
                modified_lines = _apply_hunk_to_lines(modified_lines, hunk)
                applied += 1
            except ValueError:
                pass

        new_content = '\n'.join(modified_lines)
        if had_nl and not new_content.endswith('\n'):
            new_content += '\n'

        if new_content == content:
            new_content = _apply_replacements(content, part)
        elif applied == 0:
            new_content = _apply_replacements(content, part)

        if new_content == content:
            raise ValueError(
                f'לא ניתן ליישם שינויים על {rel} – הקובץ ב-GitHub שונה מהקונטקסט. '
                'נסה לייצר diff מחדש אחרי deploy.',
            )

        full.write_text(new_content, encoding='utf-8', newline='\n')
        touched.append(rel)

    if not touched:
        raise ValueError('לא יושם אף קובץ מה-diff')
    return touched
