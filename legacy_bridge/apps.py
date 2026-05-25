from django.apps import AppConfig


class LegacyBridgeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'legacy_bridge'
    verbose_name = 'גשר שירותי לוטו (Flask)'
