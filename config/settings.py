"""
Django settings for the dental group system.

Designed to run on the clinic's own server (LAN), not in the cloud.
All deployment-specific values come from environment variables (see
.env.example); sensible development defaults are used when they are absent.
"""

import os
import sys
from pathlib import Path

from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path):
    """Minimal .env loader so the server needs no extra packages."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")


def env(key, default=None):
    return os.environ.get(key, default)


def env_bool(key, default=False):
    value = os.environ.get(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(key, default=""):
    return [item.strip() for item in env(key, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError(
            "DJANGO_SECRET_KEY is not set. Copy .env.example to .env and fill it in."
        )
    SECRET_KEY = "dev-only-insecure-key-change-me"

# The server is reached by its LAN IP / hostname, e.g. 192.168.1.10 or cia-server.
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "apps.core",
    "apps.dentists",
    "apps.patients",
    "apps.scheduling",
    "apps.clinical",
    "apps.charting",
    "apps.surgery",
    "apps.complaints",
    "apps.academy",
    "apps.billing",
    "apps.purchasing",
    "apps.stock",
    "apps.prescriptions",
    "apps.reports",
    "apps.clinics",
    "apps.specialties",
    "apps.lab",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.core.security.NetworkFenceMiddleware",
    "apps.core.security.SecurityHeadersMiddleware",
    "apps.core.middleware.CompressPagesMiddleware",
    "apps.core.middleware.SlowPageMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "apps.core.middleware.PageCacheMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.WorkingPlaceMiddleware",
    "apps.core.middleware.UserLanguageMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "apps.core.security.ReplacedSessionMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.security.IdleLogoutMiddleware",
    "apps.core.worktime.WorkTimeMiddleware",
    "apps.core.middleware.SavedMarkMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "apps.core.access.AccessControlMiddleware",
    "apps.core.middleware.ErrorRecorderMiddleware",
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
                "django.template.context_processors.i18n",
                "apps.core.context_processors.app_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Database: PostgreSQL on the clinic server is recommended. SQLite is used when
# DB_ENGINE is not set (handy for a trial run on a single PC).
if env("DB_ENGINE", "sqlite") == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("DB_NAME", "dental"),
            "USER": env("DB_USER", "dental"),
            "PASSWORD": env("DB_PASSWORD", ""),
            "HOST": env("DB_HOST", "localhost"),
            "PORT": env("DB_PORT", "5432"),
            # Each worker keeps its connection open (quicker pages) and checks it is alive before use.
            "CONN_MAX_AGE": 600,
            "CONN_HEALTH_CHECKS": True,
        }
    }
else:
    SQLITE_PATH = Path(env("SQLITE_PATH", str(BASE_DIR / "data" / "db.sqlite3")))
    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": SQLITE_PATH,
            # Several PCs saving at once: the pages keep reading while one saves (WAL), a save takes its turn at
            # once instead of failing half way ("database is locked"), and waits up to 20 s for the one before.
            "CONN_MAX_AGE": 600,  # each thread keeps its connection: no reopening the file on every page
            "CONN_HEALTH_CHECKS": True,
            "OPTIONS": {
                "timeout": 20,
                "transaction_mode": "IMMEDIATE",
                "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA temp_store=MEMORY; "
                                "PRAGMA cache_size=-32000",
            },
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Logins: wrong passwords close a login (and a device) for a while; see apps/core/security.py.
AUTHENTICATION_BACKENDS = ["apps.core.security.LockoutBackend"]
LOGIN_LOCK_AFTER = int(env("LOGIN_LOCK_AFTER", "5"))
LOGIN_IP_LOCK_AFTER = int(env("LOGIN_IP_LOCK_AFTER", "20"))
LOGIN_LOCK_MINUTES = int(env("LOGIN_LOCK_MINUTES", "15"))

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "login"

# Sessions end when the browser closes and after 12h at most (shared reception PCs).
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_AGE = 12 * 60 * 60

# Internationalisation: Arabic is the default interface language.
LANGUAGE_CODE = "ar"
LANGUAGES = [
    ("ar", _("Arabic")),
    ("en", _("English")),
]
LOCALE_PATHS = [BASE_DIR / "locale"]
FORMAT_MODULE_PATH = ["config.formats"]
TIME_ZONE = "Africa/Cairo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
if DEBUG or "test" in sys.argv[1:2]:
    # No collectstatic needed while developing or running the test suite.
    STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}

# Uploaded files (ID scans, invoices, ...). They are NOT served publicly:
# every download goes through a login-protected view (apps.core.views.protected_media).
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", str(BASE_DIR / "data" / "media")))
# Who sends the file once the view has checked who may open it: "" = Python itself (Windows, trial);
# "nginx" = the nginx in front of it (docker-compose), much lighter with many photos; "x-sendfile" = Apache.
MEDIA_SENDFILE = env("MEDIA_SENDFILE", "")
MEDIA_SENDFILE_PREFIX = env("MEDIA_SENDFILE_PREFIX", "/protected-media/")
# Full backups (Settings → Backup and export, or "python manage.py backup"): the newest BACKUP_KEEP are kept.
BACKUP_DIR = Path(env("BACKUP_DIR", str(BASE_DIR / "data" / "backups")))
BACKUP_KEEP = int(env("BACKUP_KEEP", "10"))
# A second copy of each data backup, checked against the first (another disk, a USB disk or a network folder,
# e.g. E:\CIA backup or \\NAS\backups). Empty = no second copy (Settings → Security says so).
BACKUP_COPY_DIR = env("BACKUP_COPY_DIR", "")
# The nightly copy of the photos and uploaded files (only new and changed files; best on another disk,
# e.g. E:\CIA backup\files). Empty = the "files" folder inside BACKUP_DIR.
FILES_BACKUP_DIR = env("FILES_BACKUP_DIR", "")
# "Make a backup now" works in the background when it takes long (not while the tests run).
BACKUP_IN_BACKGROUND = "test" not in sys.argv[1:2]
FILE_UPLOAD_PERMISSIONS = 0o640
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024
MAX_UPLOAD_SIZE_MB = int(env("MAX_UPLOAD_SIZE_MB", "15"))
# X-rays and CBCT reports (patient documents of that type) may be larger.
MAX_XRAY_UPLOAD_MB = int(env("MAX_XRAY_UPLOAD_MB", "60"))

# The clinic's network only: requests from other addresses are refused (apps/core/security.py). The private
# networks, the VPN range (100.64.x) and this PC by default; "*" = everyone (only behind HTTPS and a VPN).
ALLOWED_NETWORKS = env_list("ALLOWED_NETWORKS", "127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,100.64.0.0/10,"
                                                "169.254.0.0/16,::1/128,fc00::/7,fe80::/10")
# Our own nginx in front of the system (Docker): the device's address is read from what nginx sends.
TRUSTED_PROXIES = env_list("TRUSTED_PROXIES", "")

# LAN-only by default. Enable when the server is put behind HTTPS.
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "SAMEORIGIN"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True  # the pages send the token from the form, not from the cookie
if env_bool("DJANGO_HTTPS", False):
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SSL_REDIRECT", True)
    # The browser goes on using HTTPS for this server (30 days by default; 0 = off).
    SECURE_HSTS_SECONDS = int(env("DJANGO_HSTS_SECONDS", str(30 * 24 * 60 * 60)))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {},
}
# Kept on the server's disk (the console window of the server is lost when it closes):
#   errors.log      every page that stopped with an error, with the technical details (also in Problems);
#   slow-pages.log  every page that took more than SLOW_PAGE_SECONDS, to see what to speed up.
# Each file is kept to 5 MB, with the 5 before it. LOG_DIR empty = no files.
LOG_DIR = env("LOG_DIR", str(BASE_DIR / "data" / "logs"))
SLOW_PAGE_SECONDS = float(env("SLOW_PAGE_SECONDS", "3"))
if LOG_DIR and "test" not in sys.argv[1:2]:
    try:
        Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
    except OSError:
        LOG_DIR = ""
if LOG_DIR and "test" not in sys.argv[1:2]:
    for _name, _file, _level in (("errors_file", "errors.log", "ERROR"), ("slow_file", "slow-pages.log", "INFO")):
        LOGGING["handlers"][_name] = {
            "class": "logging.handlers.RotatingFileHandler", "filename": str(Path(LOG_DIR) / _file),
            "maxBytes": 5 * 1024 * 1024, "backupCount": 5, "encoding": "utf-8", "delay": True,
            "level": _level, "formatter": "plain",
        }
    LOGGING["root"]["handlers"].append("errors_file")
    LOGGING["loggers"]["clinic.slow"] = {"handlers": ["slow_file", "console"], "level": "INFO", "propagate": False}

# A test copy of the system (manage.py make_test_copy): every page shows a banner so nobody works in it by mistake.
TEST_COPY = env_bool("TEST_COPY")

# ---- Business rules (can be tuned per clinic from .env) --------------------
CLINIC = {
    # A patient arriving more than this many minutes after the appointment is "late".
    "LATE_THRESHOLD_MINUTES": int(env("LATE_THRESHOLD_MINUTES", "10")),
    # Default appointment length used when the secretary does not set one.
    "DEFAULT_APPOINTMENT_MINUTES": int(env("DEFAULT_APPOINTMENT_MINUTES", "30")),
    # Days a complaint may stay without follow-up before it is flagged overdue.
    "COMPLAINT_FOLLOW_UP_DAYS": int(env("COMPLAINT_FOLLOW_UP_DAYS", "2")),
    # Branch code used when a user has no branch assigned.
    "DEFAULT_BRANCH_CODE": env("DEFAULT_BRANCH_CODE", "CIA"),
    "CURRENCY": env("CURRENCY", "EGP"),
}
