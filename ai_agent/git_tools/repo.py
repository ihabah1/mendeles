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
        raise GitToolError(
            f"git failed ({' '.join(cmd)}): {result.stderr or result.stdout}",
        )
    return result.stdout


def _auth_clone_url() -> str:
    token = getattr(settings, 'GITHUB_TOKEN', '') or ''
    repo = getattr(settings, 'GITHUB_REPO', 'ihabah1/mendeles')
    if not token:
        raise GitToolError('GITHUB_TOKEN לא מוגדר')
    return f'https://x-access-token:{token}@github.com/{repo}.git'


def _work_dir(request_id: int) -> Path:
    base = Path(getattr(settings, 'AI_AGENT_WORK_DIR', '/tmp/ai-agent-repos'))
    base.mkdir(parents=True, exist_ok=True)
    return base / f'req-{request_id}'


def _ensure_clone(work: Path) -> Path:
    if (work / '.git').is_dir():
        _run([GIT_BIN, 'fetch', 'origin'], work)
        default = getattr(settings, 'GITHUB_DEFAULT_BRANCH', 'main')
        _run([GIT_BIN, 'checkout', default], work)
        _run([GIT_BIN, 'reset', '--hard', f'origin/{default}'], work)
        return work

    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.parent.mkdir(parents=True, exist_ok=True)
    _run([GIT_BIN, 'clone', '--depth', '1', _auth_clone_url(), str(work)], work.parent)
    return work


def _apply_diff_with_patch(repo: Path, diff_text: str) -> list[str]:
    validate_diff_paths(diff_text)
    paths = extract_paths_from_diff(diff_text)
    with tempfile.NamedTemporaryFile('w', suffix='.patch', delete=False, encoding='utf-8') as fh:
        fh.write(diff_text)
        patch_path = fh.name
    try:
        _run([GIT_BIN, 'apply', '--verbose', '--whitespace=nowarn', patch_path], repo)
    except GitToolError:
        _run([GIT_BIN, 'apply', '--verbose', '--3way', patch_path], repo)
    finally:
        Path(patch_path).unlink(missing_ok=True)
    return paths


def apply_diff_and_push(request_id: int, diff_text: str, branch_name: str) -> list[str]:
    """יוצר ענף, מיישם diff, commit, push ל-remote. לא נוגע ב-main."""
    default_branch = getattr(settings, 'GITHUB_DEFAULT_BRANCH', 'main')
    if branch_name == default_branch or branch_name.startswith('main'):
        raise GitToolError('אסור לדחוף ישירות ל-main')

    work = _ensure_clone(_work_dir(request_id))
    env = {
        **os.environ,
        'GIT_AUTHOR_NAME': 'Mandeles AI Agent',
        'GIT_AUTHOR_EMAIL': 'ai-agent@mandeles.local',
        'GIT_COMMITTER_NAME': 'Mandeles AI Agent',
        'GIT_COMMITTER_EMAIL': 'ai-agent@mandeles.local',
    }

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
