from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

# סדר קריטי: portal (ניהול) לפני web (אתר ציבורי Django)
urlpatterns = [
    path('django-admin/', admin.site.urls),
    path('', include('admin_panel.portal.urls')),
    path('', include('public_site.legacy_bridge.urls')),
    path('', include('public_site.web.urls')),
    path('accounts/', include('admin_panel.accounts.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
