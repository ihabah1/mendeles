"""Git: clone, branch, apply diff, commit, push – לעולם לא ל-main."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.utils import timezone

from admin_panel.ai_agent.git_tools.github_config import (
    clean_env_value,
    friendly_git_error,
    normalize_github_repo,
    redact_git_message,
)
from admin_panel.ai_agent.git_tools.patch_apply import apply_unified_diff_to_repo
from admin_panel.ai_agent.services.path_guard import extract_paths_from_diff, normalize_repo_path, validate_diff_paths

_GIT_BIN: str | None = None


class GitToolError(RuntimeError):
    pass


def git_bin() -> str:
    """מחזיר נתיב ל-git – נדרש ב-Railway (railpack.json → deploy.aptPackages: git)."""
    global _GIT_BIN
    if _GIT_BIN:
        return _GIT_BIN
    found = shutil.which('git')
    if not found and os.path.isfile('/usr/bin/git'):
        found = '/usr/bin/git'
    if not found:
        raise GitToolError(
            'פקודת git לא מותקנת בשרת. '
            'ב-Railway: הגדר RAILPACK_DEPLOY_APT_PACKAGES=git או פרוס מחדש עם railpack.json.',
        )
    _GIT_BIN = found
    return found


def _run(
    cmd: list[str],
    cwd: Path,
    env: dict | None = None,
    log_callback=None,
) -> str:
    if log_callback:
        shown = ' '.join(
            '***' if arg.startswith('https://') and '@github.com' in arg else arg
            for arg in cmd[:6]
        )
        if len(cmd) > 6:
            shown += ' …'
        log_callback(f'▶ git: {shown}')

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


def _repo_slug() -> str:
    repo_raw = getattr(settings, 'GITHUB_REPO', 'ihabah1/mendeles')
    try:
        return normalize_github_repo(repo_raw)
    except ValueError as exc:
        raise GitToolError(str(exc)) from exc


def _auth_clone_url() -> str:
    """Token ב-URL – עובד ב-Railway (header בלבד גורם ל-terminal prompts disabled)."""
    token = quote(_github_token(), safe='')
    return f'https://x-access-token:{token}@github.com/{_repo_slug()}.git'


def _git_env(base: dict | None = None) -> dict:
    """מבטל credential helper – האימות דרך token ב-URL של origin/clone."""
    env = {**(base or os.environ)}
    env['GIT_TERMINAL_PROMPT'] = '0'
    env['GIT_CONFIG_COUNT'] = '1'
    env['GIT_CONFIG_KEY_0'] = 'credential.helper'
    env['GIT_CONFIG_VALUE_0'] = ''
    return env


def _ensure_origin_authenticated(work: Path, env: dict, log_callback=None) -> None:
    _run(
        [git_bin(), 'remote', 'set-url', 'origin', _auth_clone_url()],
        work,
        env=env,
        log_callback=log_callback,
    )


def _work_dir(request_id: int) -> Path:
    base = Path(getattr(settings, 'AI_AGENT_WORK_DIR', '/tmp/ai-agent-repos'))
    base.mkdir(parents=True, exist_ok=True)
    return base / f'req-{request_id}'


def ensure_github_context_clone() -> Path:
    """Clone מעודכן של origin/main – לקונטקסט Gemini וליישום patch."""
    return _ensure_clone(_work_dir(0))


def _ensure_clone(work: Path, log_callback=None) -> Path:
    env = _git_env()
    if (work / '.git').is_dir():
        _ensure_origin_authenticated(work, env, log_callback=log_callback)
        _run([git_bin(), 'fetch', 'origin'], work, env=env, log_callback=log_callback)
        default = getattr(settings, 'GITHUB_DEFAULT_BRANCH', 'main')
        _run([git_bin(), 'checkout', default], work, env=env, log_callback=log_callback)
        _run(
            [git_bin(), 'reset', '--hard', f'origin/{default}'],
            work,
            env=env,
            log_callback=log_callback,
        )
        return work

    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [git_bin(), 'clone', '--depth', '1', _auth_clone_url(), str(work)],
        work.parent,
        env=env,
        log_callback=log_callback,
    )
    _ensure_origin_authenticated(work, env, log_callback=log_callback)
    return work


def _apply_diff_with_patch(repo: Path, diff_text: str, log_callback=None) -> list[str]:
    validate_diff_paths(diff_text)
    paths = extract_paths_from_diff(diff_text)
    with tempfile.NamedTemporaryFile('w', suffix='.patch', delete=False, encoding='utf-8') as fh:
        fh.write(diff_text)
        patch_path = fh.name
    try:
        _run(
            [git_bin(), 'apply', '--verbose', '--whitespace=nowarn', '--ignore-space-change', patch_path],
            repo,
            log_callback=log_callback,
        )
        return paths
    except GitToolError:
        try:
            if log_callback:
                log_callback('▶ git apply נכשל – מנסה --3way…')
            _run([git_bin(), 'apply', '--verbose', '--3way', patch_path], repo, log_callback=log_callback)
            return paths
        except GitToolError:
            pass
    finally:
        Path(patch_path).unlink(missing_ok=True)

    try:
        return apply_unified_diff_to_repo(repo, diff_text)
    except ValueError as exc:
        raise GitToolError(str(exc)) from exc


def apply_diff_and_push(
    request_id: int,
    diff_text: str,
    branch_name: str,
    log_callback=None,
) -> list[str]:
    """יוצר ענף, מיישם diff, commit, push ל-remote. לא נוגע ב-main."""

    def log(msg: str) -> None:
        if log_callback:
            log_callback(msg)

    default_branch = getattr(settings, 'GITHUB_DEFAULT_BRANCH', 'main')
    if branch_name == default_branch or branch_name.startswith('main'):
        raise GitToolError('אסור לדחוף ישירות ל-main')

    log('מתחיל clone / fetch מ-GitHub (origin/main)…')
    work = _ensure_clone(_work_dir(request_id), log_callback=log)
    log('clone מעודכן – מכין ענף מקומי…')
    env = _git_env({
        'GIT_AUTHOR_NAME': 'Mandeles AI Agent',
        'GIT_AUTHOR_EMAIL': 'ai-agent@mandeles.local',
        'GIT_COMMITTER_NAME': 'Mandeles AI Agent',
        'GIT_COMMITTER_EMAIL': 'ai-agent@mandeles.local',
    })
    _ensure_origin_authenticated(work, env, log_callback=log)

    log(f'checkout לענף {branch_name}…')
    _run([git_bin(), 'checkout', '-B', branch_name], work, env=env, log_callback=log)
    log('מיישם diff על הקבצים (git apply / Python)…')
    touched = _apply_diff_with_patch(work, diff_text, log_callback=log)
    log(f'patch הוחל על {len(touched)} קבצים')

    status = _run([git_bin(), 'status', '--porcelain'], work, env=env, log_callback=log)
    if not status.strip():
        raise GitToolError('אין שינויים לאחר יישום ה-diff')

    log('git add + commit…')
    _run(
        [git_bin(), 'add'] + [normalize_repo_path(p) for p in touched],
        work,
        env=env,
        log_callback=log,
    )
    _run(
        [git_bin(), 'commit', '-m', f'ai-agent: change request #{request_id}'],
        work,
        env=env,
        log_callback=log,
    )
    log(f'דוחף ל-origin/{branch_name}…')
    _run([git_bin(), 'push', '-u', 'origin', branch_name], work, env=env, log_callback=log)
    log('push הושלם')
    return touched
