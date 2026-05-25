from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

# סדר קריטי: portal (ניהול) לפני web (React)
urlpatterns = [
    path('django-admin/', admin.site.urls),
    path('', include('portal.urls')),
    path('', include('legacy_bridge.urls')),
    path('', include('web.urls')),
    path('accounts/', include('accounts.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
