from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse

from accounts.permissions import is_portal_admin


class AdminDashboardGuardMiddleware:
    """Protect /manage/* routes – admin users only."""

    def __init__(self, get_response):
        self.get_response = get_response
        prefix = f"/{settings.ADMIN_DASHBOARD_PREFIX}/"
        self.protected_prefix = prefix
        self.login_path = reverse('portal:login')

    def __call__(self, request):
        path = request.path
        if path.startswith(self.protected_prefix) and not path.endswith('/login/'):
            user = request.user
            if not user.is_authenticated:
                return redirect(f'{self.login_path}?next={path}')
            if not is_portal_admin(user):
                return redirect(self.login_path)
        response = self.get_response(request)
        if path.startswith(self.protected_prefix):
            response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response['Pragma'] = 'no-cache'
        return response
