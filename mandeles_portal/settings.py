"""
Django settings for Mandeles Portal – WEB + mobile-responsive admin.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv(
    'DJANGO_SECRET_KEY',
    'dev-only-change-in-production-mandeles-2026',
)

DEBUG = os.getenv('DJANGO_DEBUG', 'true').lower() in ('1', 'true', 'yes')

ALLOWED_HOSTS = [
    h.strip()
    for h in os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
    if h.strip()
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'accounts',
    'portal',
    'web',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'portal.middleware.AdminDashboardGuardMiddleware',
]

ROOT_URLCONF = 'mandeles_portal.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'portal.context_processors.dashboard_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'mandeles_portal.wsgi.application'
ASGI_APPLICATION = 'mandeles_portal.asgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'data' / 'portal.db',
    }
}

AUTH_USER_MODEL = 'accounts.User'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 4}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'he'
TIME_ZONE = 'Asia/Jerusalem'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'portal:login'
LOGIN_REDIRECT_URL = 'portal:dashboard'
LOGOUT_REDIRECT_URL = 'portal:login'

SESSION_COOKIE_AGE = 60 * 60 * 12
SESSION_SAVE_EVERY_REQUEST = True

# Custom admin dashboard path (not /admin/)
ADMIN_DASHBOARD_PREFIX = 'manage'

APP_VERSION = '1.2.2'

# מנהל יחיד לדשבורד /manage/
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'admin@admin.com')
