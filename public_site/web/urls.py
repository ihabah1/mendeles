from django.urls import path
from django.views.generic import RedirectView

from . import auth_api, public_views

# אתר ציבורי – Django בלבד (ללא React)
urlpatterns = [
    path('api/auth/csrf/', auth_api.csrf, name='auth-csrf'),
    path('api/auth/me/', auth_api.me, name='auth-me'),
    path('api/auth/register/', auth_api.register_view, name='auth-register'),
    path('api/auth/login/', auth_api.login_view, name='auth-login'),
    path('api/auth/logout/', auth_api.logout_view, name='auth-logout'),
    path('api/auth/profile/', auth_api.profile_view, name='auth-profile'),
    path('dashboard/', RedirectView.as_view(url='/manage/customers/', permanent=False)),
    path('777/', RedirectView.as_view(url='/', permanent=False)),
    path('new_stite.html', RedirectView.as_view(url='/', permanent=True)),
    path('auth.html', RedirectView.as_view(url='/login/', permanent=True)),
    path('', public_views.public_home, name='public-home'),
    path('toto/', public_views.public_toto, name='public-toto'),
    path('login/', public_views.public_login, name='public-login'),
    path('register/', public_views.public_register, name='public-register'),
    path('account/', public_views.public_account, name='public-account'),
    path('about/', public_views.public_about, name='public-about'),
    path('legal/', public_views.public_legal, name='public-legal'),
    path('accessibility/', public_views.public_accessibility, name='public-a11y'),
    # דפים שנוצרו ע"י ה-AI – templates/web/pages/<slug>.html
    path('p/', public_views.public_pages_index, name='public-pages'),
    path('p/<slug:slug>/', public_views.public_page, name='public-page'),
    # הפניות ישנות מ-React SPA
    path('app/', RedirectView.as_view(url='/', permanent=True)),
    path('app/<path:subpath>/', RedirectView.as_view(url='/', permanent=True)),
    # ברירת מחדל אחרונה: דף שנוצר בניהול שינויים בכתובת נקייה /<slug>/
    # (נבדק רק אם אף נתיב אחר לא תפס; 404 אם אין template תואם)
    path('<slug:slug>/', public_views.public_page, name='public-page-root'),
]
