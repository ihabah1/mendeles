from django.apps import AppConfig


class AiAgentConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ai_agent'
    verbose_name = 'סוכן AI לשינויי תוכן'

    def ready(self) -> None:
        from django.conf import settings

        if getattr(settings, 'AI_AGENT_ENABLED', False):
            from ai_agent.services.job_queue import ensure_queue_worker

            ensure_queue_worker()
