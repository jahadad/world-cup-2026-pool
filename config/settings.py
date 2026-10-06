import os
import sys
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-key-set-SECRET_KEY-in-railway")
DEBUG = os.environ.get("DEBUG", "0") == "1"
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "*").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "prode",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        conn_health_checks=True,
    )
}

# Solo largo mínimo: es un prode entre amigos, no un banco.
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 6},
    },
]

LANGUAGE_CODE = "en-us"
# Audiencia global: el server habla UTC y el navegador de cada visitante
# convierte a su hora local (ver base.html).
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
# El storage con manifest exige collectstatic previo; en tests y dev no corre.
if DEBUG or "test" in sys.argv:
    STORAGES["staticfiles"]["BACKEND"] = "django.contrib.staticfiles.storage.StaticFilesStorage"

# Cache en la base: compartida entre los workers de gunicorn (para el
# throttling de login). La tabla la crea createcachetable en start.sh.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "prode_cache",
    }
}
if DEBUG or "test" in sys.argv:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "fixture"
LOGOUT_REDIRECT_URL = "login"

# El torneo dura 5 semanas y media: nadie debe quedar deslogueado en el medio.
SESSION_COOKIE_AGE = 60 * 60 * 24 * 60  # 60 días

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# En Railway: fallar fuerte si falta configuración crítica, y cookies solo-HTTPS.
if "RAILWAY_ENVIRONMENT" in os.environ:
    from django.core.exceptions import ImproperlyConfigured

    if SECRET_KEY.startswith("dev-only-insecure"):
        raise ImproperlyConfigured("SECRET_KEY is not set in production.")
    if not os.environ.get("DATABASE_URL"):
        raise ImproperlyConfigured("DATABASE_URL is not set in production.")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# --- Reglas del prode (todas configurables por env var) ---
PRODE_LOCK_MINUTES = int(os.environ.get("LOCK_MINUTES", "5"))
PRODE_INVITE_CODE = os.environ.get("INVITE_CODE", "PRODE2026")
# Estilo MercadoPago (ratio 2:1): premia consistencia, mejor para casuales.
PRODE_POINTS_EXACT = int(os.environ.get("POINTS_EXACT", "6"))
PRODE_POINTS_OUTCOME = int(os.environ.get("POINTS_OUTCOME", "3"))
