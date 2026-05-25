"""ניקוי משתני GitHub – Railway לפעמים שומר רווח/שורה חדשה בסוף הערך."""
from __future__ import annotations

import re


def clean_env_value(value: str) -> str:
    if not value:
        return ''
    return value.strip().replace('\r', '').replace('\n', '')


def normalize_github_repo(repo: str) -> str:
    r = clean_env_value(repo).strip('/')
    if r.endswith('.git'):
        r = r[:-4]
    if '/' not in r or r.count('/') != 1:
        raise ValueError(f'GITHUB_REPO לא תקין (צריך owner/name): {repo!r}')
    return r


def redact_git_message(text: str) -> str:
    if not text:
        return ''
    t = text
    t = re.sub(
        r'https://[^\s@]+@github\.com/[^\s]+',
        'https://***@github.com/REDACTED',
        t,
    )
    t = re.sub(r'github_pat_[A-Za-z0-9_]+', 'github_pat_***', t)
    t = re.sub(r'x-access-token:[^\s@]+', 'x-access-token:***', t)
    return t
