import threading

from django.apps import AppConfig


class AiAgentConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'admin_panel.ai_agent'
    verbose_name = 'סוכן AI לשינויי תוכן'

    def ready(self) -> None:
        from django.conf import settings

        if not getattr(settings, 'AI_AGENT_ENABLED', False):
            return
        # לא לגעת ב-DB כאן – manage.py migrate קורא ל-ready לפני שהטבלה קיימת
        from admin_panel.ai_agent.services.job_queue import start_worker_when_db_ready

        threading.Thread(
            target=start_worker_when_db_ready,
            name='ai-queue-init',
            daemon=True,
        ).start()
