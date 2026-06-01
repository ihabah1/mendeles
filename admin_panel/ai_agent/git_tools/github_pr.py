"""יצירת Pull Request ב-GitHub – לא push ל-main."""
from __future__ import annotations

from django.conf import settings

from admin_panel.ai_agent.git_tools.github_config import clean_env_value, normalize_github_repo


class GitHubPRError(RuntimeError):
    pass


def create_pull_request(
    *,
    branch_name: str,
    title: str,
    body: str,
) -> tuple[int, str]:
    token = clean_env_value(getattr(settings, 'GITHUB_TOKEN', '') or '')
    try:
        repo_name = normalize_github_repo(getattr(settings, 'GITHUB_REPO', 'ihabah1/mendeles'))
    except ValueError as exc:
        raise GitHubPRError(str(exc)) from exc
    base = clean_env_value(getattr(settings, 'GITHUB_DEFAULT_BRANCH', 'main') or 'main')

    if not token:
        raise GitHubPRError('GITHUB_TOKEN לא מוגדר')
    if branch_name == base:
        raise GitHubPRError('אסור לפתוח PR מ-main ל-main')

    try:
        from github import Github
    except ImportError as exc:
        raise GitHubPRError('חבילת PyGithub לא מותקנת') from exc

    gh = Github(token)
    repo = gh.get_repo(repo_name)
    pr = repo.create_pull(
        title=title[:255],
        body=body,
        head=branch_name,
        base=base,
    )
    return pr.number, pr.html_url


def _github_client():
    token = clean_env_value(getattr(settings, 'GITHUB_TOKEN', '') or '')
    if not token:
        raise GitHubPRError('GITHUB_TOKEN לא מוגדר')
    try:
        from github import Github
    except ImportError as exc:
        raise GitHubPRError('חבילת PyGithub לא מותקנת') from exc
    return Github(token), normalize_github_repo(getattr(settings, 'GITHUB_REPO', 'ihabah1/mendeles'))


def merge_pull_request(pr_number: int) -> str:
    """ממזג PR ל-main. מחזיר sha או הודעה אם כבר מוזג."""
    gh, repo_name = _github_client()
    repo = gh.get_repo(repo_name)
    pr = repo.get_pull(pr_number)
    if pr.merged:
        return pr.merge_commit_sha or 'already-merged'
    try:
        result = pr.merge(merge_method='merge')
    except Exception as exc:
        pr = repo.get_pull(pr_number)
        if pr.merged:
            return pr.merge_commit_sha or 'already-merged'
        raise GitHubPRError(f'מיזוג PR נכשל: {exc}') from exc
    if not result.merged:
        raise GitHubPRError('GitHub לא אישר מיזוג – ייתכן שיש קונפליקטים')
    return result.sha or 'merged'
