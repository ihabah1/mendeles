from django.conf import settings


def dashboard_context(request):
    prefix = settings.ADMIN_DASHBOARD_PREFIX
    return {
        'ADMIN_PREFIX': prefix,
        'APP_VERSION': settings.APP_VERSION,
        'pending_orders_count': 0,
    }
