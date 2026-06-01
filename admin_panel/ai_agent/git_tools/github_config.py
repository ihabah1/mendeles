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


def friendly_git_error(stderr: str) -> str | None:
    """הודעה בעברית לשגיאות נפוצות."""
    low = (stderr or '').lower()
    if '403' in low or ('permission' in low and 'denied' in low):
        return (
            'GitHub דחה push (403): ל-GITHUB_TOKEN חסרות הרשאות כתיבה. '
            'צור Personal Access Token חדש עם: Contents (Read and write) + '
            'Pull requests (Read and write) על repo ihabah1/mendeles, '
            'עדכן ב-Railway (בלי רווח בסוף), ואם Fine-grained – אשר SSO אם מופיע.'
        )
    if 'terminal prompts disabled' in low or 'could not read username' in low:
        return (
            'Git לא קיבל credentials: ודא ש-GITHUB_TOKEN מוגדר ב-Railway '
            '(לא ריק) ועשה Redeploy אחרי העדכון.'
        )
    if (
        '401' in low
        or 'invalid credentials' in low
        or 'authentication failed' in low
        or 'bad credentials' in low
    ):
        return (
            'GitHub דחה התחברות: GITHUB_TOKEN ב-Railway לא תקין, פג תוקף, '
            'או בוטל. צור token חדש (Contents + Pull requests: Read and write), '
            'הדבק רק ב-Railway → Variables → GITHUB_TOKEN, ועשה Redeploy.'
        )
    return None


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
