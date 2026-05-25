from django.urls import path
from django.views.generic import RedirectView

from . import auth_api, public_views, views

# אתר ציבורי: תבניות Django ב-/ | React SPA ישן: /app/
urlpatterns = [
    path('api/auth/csrf/', auth_api.csrf, name='auth-csrf'),
    path('api/auth/me/', auth_api.me, name='auth-me'),
    path('api/auth/register/', auth_api.register_view, name='auth-register'),
    path('api/auth/login/', auth_api.login_view, name='auth-login'),
    path('api/auth/logout/', auth_api.logout_view, name='auth-logout'),
    path('dashboard/', RedirectView.as_view(url='/manage/customers/', permanent=False)),
    path('777/', RedirectView.as_view(url='/', permanent=False)),
    path('', public_views.public_home, name='public-home'),
    path('toto/', public_views.public_toto, name='public-toto'),
    path('login/', public_views.public_login, name='public-login'),
    path('register/', public_views.public_register, name='public-register'),
    path('about/', public_views.public_about, name='public-about'),
    path('legal/', public_views.public_legal, name='public-legal'),
    path('accessibility/', public_views.public_accessibility, name='public-a11y'),
    path('app/', views.spa, name='spa-legacy'),
    path('app/<path:subpath>/', views.spa, name='spa-legacy-sub'),
]
