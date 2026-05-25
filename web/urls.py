from django.urls import path
from django.views.generic import RedirectView

from . import auth_api, views

# רק נתיבי React מפורשים – /manage/ לא נכנס ל-SPA (דשבורד Django)
urlpatterns = [
    path('api/auth/csrf/', auth_api.csrf, name='auth-csrf'),
    path('api/auth/me/', auth_api.me, name='auth-me'),
    path('api/auth/register/', auth_api.register_view, name='auth-register'),
    path('api/auth/login/', auth_api.login_view, name='auth-login'),
    path('api/auth/logout/', auth_api.logout_view, name='auth-logout'),
    path('dashboard/', RedirectView.as_view(url='/manage/customers/', permanent=False)),
    path('777/', RedirectView.as_view(url='/', permanent=False)),
    path('', views.spa, name='spa-home'),
    path('toto/', views.spa, name='spa-toto'),
    path('login/', views.spa, name='spa-login'),
    path('register/', views.spa, name='spa-register'),
    path('about/', views.spa, name='spa-about'),
    path('legal/', views.spa, name='spa-legal'),
    path('accessibility/', views.spa, name='spa-a11y'),
]
