"""תאימות לאחור – כל ההרצות עוברות לתור."""
from __future__ import annotations

from collections.abc import Callable

from admin_panel.ai_agent.models import AIChangeRequest, AIJob
from admin_panel.ai_agent.services.job_queue import enqueue, ensure_queue_worker

_JOB_TYPE_MAP = {
    'generate_diff_for_request': AIJob.JobType.GENERATE_DIFF,
    'approve_and_create_pr': AIJob.JobType.CREATE_PR,
    'merge_pr_for_request': AIJob.JobType.MERGE_PR,
}


def run_ai_job(
    request_id: int,
    fn: Callable[[AIChangeRequest], AIChangeRequest],
    *,
    resume: bool = True,  # noqa: ARG001
) -> AIJob:
    """מוסיף לתור במקום thread – resume נשמר לתאימות API."""
    ensure_queue_worker()
    job_type = _JOB_TYPE_MAP.get(getattr(fn, '__name__', ''), '')
    if not job_type:
        raise ValueError(f'פונקציה לא נתמכת בתור: {fn}')
    return enqueue(request_id, job_type)
