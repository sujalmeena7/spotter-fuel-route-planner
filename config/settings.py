"""Django settings for spotter fuel route planner project."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env if present
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("SECRET_KEY", "insecure-dev-secret-key-change-in-prod")
DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "t", "yes")

allowed_hosts_raw = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0")
ALLOWED_HOSTS = [h.strip() for h in allowed_hosts_raw.split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "drf_spectacular",
    # Local apps
    "apps.stations.apps.StationsConfig",
    "apps.routing.apps.RoutingConfig",
    "apps.planner.apps.PlannerConfig",
    "apps.web.apps.WebConfig",
]

MIDDLEWARE = [
    "apps.planner.middleware.ResponseTimeMiddleware",
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
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Cache configuration
redis_url = os.getenv("REDIS_URL")
if redis_url:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": redis_url,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "spotter-cache",
        }
    }

# Django REST Framework
REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.planner.exceptions.custom_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
    },
}

# drf-spectacular
SPECTACULAR_SETTINGS = {
    "TITLE": "Spotter Fuel Route API",
    "DESCRIPTION": "Optimal fuel stop planning along routes for long-haul trucking fleets",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# Fleet logistics & optimization parameters
TANK_GALLONS = int(os.getenv("TANK_GALLONS", "50"))
MPG = float(os.getenv("MPG", "10"))
CORRIDOR_MILES = float(os.getenv("CORRIDOR_MILES", "10"))
ORIGIN_RADIUS_MILES = float(os.getenv("ORIGIN_RADIUS_MILES", "25"))
ORS_API_KEY = os.getenv("ORS_API_KEY", "").strip()
