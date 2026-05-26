"""הרצת משימות AI ברקע – מאפשר polling ללוגים בזמן אמת."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from django.db import close_old_connections

from ai_agent.models import AIChangeRequest

logger = logging.getLogger(__name__)


def run_ai_job(request_id: int, fn: Callable[[AIChangeRequest], AIChangeRequest], *, resume: bool = True) -> None:
    """מריץ fn ב-thread נפרד; fn אחראי לעדכון סטטוס/שגיאה ב-DB."""

    def worker() -> None:
        close_old_connections()
        try:
            obj = AIChangeRequest.objects.get(pk=request_id)
            fn(obj, resume=resume)
        except AIChangeRequest.DoesNotExist:
            logger.warning('AI job: request #%s not found', request_id)
        except Exception as exc:
            logger.exception('AI job failed for request #%s', request_id)
            try:
                obj = AIChangeRequest.objects.get(pk=request_id)
                if obj.status in (
                    AIChangeRequest.Status.GENERATING,
                    AIChangeRequest.Status.PR_CREATING,
                    AIChangeRequest.Status.APPROVED,
                ):
                    obj.status = AIChangeRequest.Status.FAILED
                    obj.error_message = str(exc)[:500]
                    obj.append_log(f'שגיאה לא צפויה: {exc}')
            except AIChangeRequest.DoesNotExist:
                pass
        finally:
            close_old_connections()

    threading.Thread(target=worker, daemon=True).start()
