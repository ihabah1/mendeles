from django.urls import path, re_path

from . import views

urlpatterns = [
    # דפדפן: /admin/ → דשבורד Django; /admin/stats → API ארנק
    path('admin/', views.admin_browser_entry),
    re_path(r'^admin/(?P<path>.+)$', views.proxy_wallet_admin),
    re_path(r'^auth/(?P<path>.*)$', views.proxy_auth),
    re_path(r'^lotto/(?P<path>.*)$', views.proxy_lotto),
    re_path(r'^engine/(?P<path>.*)$', views.proxy_engine),
    # API לוטו (server.py) – נתיבים מפורשים (לפני catch-all של Django)
    path('api/health', views.proxy_lotto_api, {'path': 'health'}),
    path('api/check', views.proxy_lotto_api, {'path': 'check'}),
    path('api/stats', views.proxy_lotto_api, {'path': 'stats'}),
    path('api/next-draw', views.proxy_lotto_api, {'path': 'next-draw'}),
    re_path(r'^api/suggest/(?P<path>.*)$', views.proxy_lotto_api),
    re_path(r'^api/payment/(?P<path>.*)$', views.proxy_lotto_api),
    re_path(r'^api/webhook/(?P<path>.*)$', views.proxy_lotto_api),
    re_path(r'^api/admin/(?P<path>.*)$', views.proxy_lotto_api),
    # דפי HTML קלאסיים
    path('classic/', views.classic_page, {'page': ''}, name='classic_home'),
    path('classic/<path:page>', views.classic_page, name='classic_page'),
    path('legacy/status/', views.integration_status, name='legacy_status'),
    path('manage/integration/', views.integration_page, name='legacy_integration'),
    path('manage/integration/fix/', views.integration_fix, name='legacy_integration_fix'),
    path('manage/integration/toggle/', views.integration_toggle, name='legacy_integration_toggle'),
    path('manage/integration/logs/', views.integration_logs, name='legacy_integration_logs'),
]
