"""Git: clone, branch, apply diff, commit, push – לעולם לא ל-main."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from ai_agent.git_tools.github_config import (
    clean_env_value,
    friendly_git_error,
    normalize_github_repo,
    redact_git_message,
)
from ai_agent.git_tools.patch_apply import apply_unified_diff_to_repo
from ai_agent.services.path_guard import extract_paths_from_diff, normalize_repo_path, validate_diff_paths

GIT_BIN = 'git'


class GitToolError(RuntimeError):
    pass


def _run(cmd: list[str], cwd: Path, env: dict | None = None) -> str:
    result = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if result.returncode != 0:
        raw = result.stderr or result.stdout or ''
        friendly = friendly_git_error(raw)
        if friendly:
            raise GitToolError(friendly)
        err = redact_git_message(raw)
        cmd_safe = ' '.join(
            '***' if arg.startswith('https://') and '@github.com' in arg else arg
            for arg in cmd
        )
        raise GitToolError(f'git failed ({cmd_safe}): {err}')
    return result.stdout


def _github_token() -> str:
    token = clean_env_value(getattr(settings, 'GITHUB_TOKEN', '') or '')
    if not token:
        raise GitToolError('GITHUB_TOKEN לא מוגדר')
    return token


def _auth_clone_url() -> str:
    token = _github_token()
    token = clean_env_value(getattr(settings, 'GITHUB_TOKEN', '') or '')
    repo_raw = getattr(settings, 'GITHUB_REPO', 'ihabah1/mendeles')
    try:
        repo = normalize_github_repo(repo_raw)
    except ValueError as exc:
        raise GitToolError(str(exc)) from exc
    return f'https://x-access-token:{token}@github.com/{repo}.git'


def _git_env(base: dict | None = None) -> dict:
    """מבטל credential helper ומוסיף Authorization לכל פקודת git ל-GitHub."""
    token = _github_token()
    env = {**(base or os.environ)}
    env['GIT_TERMINAL_PROMPT'] = '0'
    env['GIT_CONFIG_COUNT'] = '2'
    env['GIT_CONFIG_KEY_0'] = 'credential.helper'
    env['GIT_CONFIG_VALUE_0'] = ''
    env['GIT_CONFIG_KEY_1'] = 'http.https://github.com/.extraheader'
    env['GIT_CONFIG_VALUE_1'] = f'AUTHORIZATION: bearer {token}'
    return env


def _ensure_origin_authenticated(work: Path, env: dict) -> None:
    """מגדיר מחדש origin עם ה-token – אחרת fetch/push עלולים לרוץ בלי הרשאות."""
    _run([GIT_BIN, 'remote', 'set-url', 'origin', _auth_clone_url()], work, env=env)


def _work_dir(request_id: int) -> Path:
    base = Path(getattr(settings, 'AI_AGENT_WORK_DIR', '/tmp/ai-agent-repos'))
    base.mkdir(parents=True, exist_ok=True)
    return base / f'req-{request_id}'


def ensure_github_context_clone() -> Path:
    """Clone מעודכן של origin/main – לקונטקסט Gemini וליישום patch."""
    return _ensure_clone(_work_dir(0))


def _ensure_clone(work: Path) -> Path:
    env = _git_env()
    if (work / '.git').is_dir():
        _ensure_origin_authenticated(work, env)
        _run([GIT_BIN, 'fetch', 'origin'], work, env=env)
        default = getattr(settings, 'GITHUB_DEFAULT_BRANCH', 'main')
        _run([GIT_BIN, 'checkout', default], work, env=env)
        _run([GIT_BIN, 'reset', '--hard', f'origin/{default}'], work, env=env)
        return work

    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.parent.mkdir(parents=True, exist_ok=True)
    _run([GIT_BIN, 'clone', '--depth', '1', _auth_clone_url(), str(work)], work.parent, env=env)
    _ensure_origin_authenticated(work, env)
    return work


def _apply_diff_with_patch(repo: Path, diff_text: str) -> list[str]:
    validate_diff_paths(diff_text)
    paths = extract_paths_from_diff(diff_text)
    with tempfile.NamedTemporaryFile('w', suffix='.patch', delete=False, encoding='utf-8') as fh:
        fh.write(diff_text)
        patch_path = fh.name
    try:
        _run(
            [GIT_BIN, 'apply', '--verbose', '--whitespace=nowarn', '--ignore-space-change', patch_path],
            repo,
        )
        return paths
    except GitToolError:
        try:
            _run([GIT_BIN, 'apply', '--verbose', '--3way', patch_path], repo)
            return paths
        except GitToolError:
            pass
    finally:
        Path(patch_path).unlink(missing_ok=True)

    try:
        return apply_unified_diff_to_repo(repo, diff_text)
    except ValueError as exc:
        raise GitToolError(str(exc)) from exc


def apply_diff_and_push(request_id: int, diff_text: str, branch_name: str) -> list[str]:
    """יוצר ענף, מיישם diff, commit, push ל-remote. לא נוגע ב-main."""
    default_branch = getattr(settings, 'GITHUB_DEFAULT_BRANCH', 'main')
    if branch_name == default_branch or branch_name.startswith('main'):
        raise GitToolError('אסור לדחוף ישירות ל-main')

    work = _ensure_clone(_work_dir(request_id))
    env = _git_env({
        'GIT_AUTHOR_NAME': 'Mandeles AI Agent',
        'GIT_AUTHOR_EMAIL': 'ai-agent@mandeles.local',
        'GIT_COMMITTER_NAME': 'Mandeles AI Agent',
        'GIT_COMMITTER_EMAIL': 'ai-agent@mandeles.local',
    })
    _ensure_origin_authenticated(work, env)

    _run([GIT_BIN, 'checkout', '-B', branch_name], work, env=env)
    touched = _apply_diff_with_patch(work, diff_text)

    status = _run([GIT_BIN, 'status', '--porcelain'], work, env=env)
    if not status.strip():
        raise GitToolError('אין שינויים לאחר יישום ה-diff')

    _run([GIT_BIN, 'add'] + [normalize_repo_path(p) for p in touched], work, env=env)
    _run(
        [GIT_BIN, 'commit', '-m', f'ai-agent: change request #{request_id}'],
        work,
        env=env,
    )
    _run([GIT_BIN, 'push', '-u', 'origin', branch_name], work, env=env)
    return touched
