from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache

from admin_panel.accounts.permissions import is_portal_admin


def admin_required(view_func):
    @never_cache
    @login_required
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not is_portal_admin(request.user):
            return redirect('portal:login')
        return view_func(request, *args, **kwargs)

    return _wrapped
