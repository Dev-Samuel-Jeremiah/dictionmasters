"""
Django settings for the Diction Masters project.

Diction Masters gives every Nigerian school child a private British
English tutor: video lessons, audio drills, speaking practice, teacher
feedback, and school-controlled access — all class-scoped so a child
only ever sees their own class.

This file is intentionally kept simple and explicit. As the project
grows (accounts, schools, lessons, assessments, ...) each new domain
becomes its own app under `apps/` and gets one line in INSTALLED_APPS.
"""

import os
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / "subdir"
BASE_DIR = Path(__file__).resolve().parent.parent

# Secrets for local development live in .env (git-ignored). Real
# environment variables still win, so production never reads the file.
load_dotenv(BASE_DIR / ".env", override=False)


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

# One switch decides how the site runs. Development is the default, so
# nothing has to be set to work on a laptop; the server sets
# DJANGO_ENV=production and everything below tightens up.
DJANGO_ENV = os.environ.get("DJANGO_ENV", "development").strip().lower()
PRODUCTION = DJANGO_ENV == "production"

# Running the test suite, by manage.py test or pytest.
TESTING = "test" in sys.argv or bool(os.environ.get("PYTEST_CURRENT_TEST"))


def env_flag(name, default):
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Core / security
# ---------------------------------------------------------------------------

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-secret-key-change-me")

DEBUG = env_flag("DJANGO_DEBUG", not PRODUCTION)

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

# The address the world uses. QR codes printed in the books point here, so
# a code made on a laptop still works for a child holding the book.
SITE_URL = os.environ.get("DJANGO_SITE_URL", "https://www.dictionmasters.app").rstrip("/")

# Full origins, needed for form posts over HTTPS, e.g.
# "https://dictionmasters.com,https://www.dictionmasters.com".
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

if PRODUCTION and not TESTING:
    # Rather than start with a key everyone can read, or serve every
    # host, the site refuses to boot until production is set up properly.
    if SECRET_KEY == "dev-insecure-secret-key-change-me":
        raise ImproperlyConfigured("Set DJANGO_SECRET_KEY before running in production.")
    if not ALLOWED_HOSTS:
        raise ImproperlyConfigured("Set DJANGO_ALLOWED_HOSTS to your domain(s) before running in production.")

# Our own pages only: the header's Phonemic Chart and Quick Words open in
# a panel over the page you're on. Other sites still can't frame ours.
X_FRAME_OPTIONS = "SAMEORIGIN"

if not DEBUG:
    # Behind nginx or a load balancer, this is how Django knows the
    # visitor arrived over HTTPS.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_flag("DJANGO_SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # A year, and tell browsers to remember it for subdomains too. Set
    # DJANGO_HSTS_SECONDS=0 while testing a new domain over plain HTTP.
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", 31536000))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_flag("DJANGO_HSTS_SUBDOMAINS", True)
    SECURE_HSTS_PRELOAD = env_flag("DJANGO_HSTS_PRELOAD", True)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    SESSION_COOKIE_HTTPONLY = True


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Lets the project override widget templates, e.g. the admin file input.
    "django.forms",
]

# First-party apps live under apps/<name> and are added here one at a
# time as each section of the product is built. Keeping them in their
# own namespace (apps.landing, apps.schools, apps.lessons, ...) keeps
# the top level of the project uncluttered as it grows.
LOCAL_APPS = [
    "apps.landing",
    "apps.accounts",
    "apps.schools",
    "apps.learning_tools",
    "apps.platform_search",
    "apps.book",
    "apps.videos",
    "apps.tricks",
    "apps.reference_library",
    "apps.diction_library",
    "apps.diction_radio",
    "apps.daily_practice",
    "apps.learning_modules",
    "apps.reading_club",
    "apps.echospell",
    "apps.quick_words",
    "apps.tutor",
    "apps.assessments",
    "apps.clash",
    "apps.console",
    "apps.manage",
    "apps.billing",
]

THIRD_PARTY_APPS = []

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # The Android and iPhone apps: welcome screen, app-store payment rules (apps/landing/native_app.py).
    "apps.landing.native_app.NativeAppMiddleware",
    # Learning tools need a running free trial or a paid plan (apps/billing).
    "apps.billing.middleware.SubscriptionRequiredMiddleware",
]

# Serves the site's own CSS, JS and images in production, so no separate
# web server is needed for them; uploads live on R2. In development
# Django's own static handler does it, straight from the source files.
if not DEBUG:
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Project-wide templates live in /templates. Each app may also
        # ship its own templates/<app_name>/ directory, which Django
        # finds automatically via app_dirs below.
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.landing.context_processors.branding",
                "apps.landing.context_processors.nav",
                "apps.billing.context_processors.billing",
                "apps.landing.native_app.context",
            ],
            # {{ colour|palette }} everywhere, for colours stored in the database.
            "builtins": ["apps.landing.templatetags.palette"],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
#
# The site runs on PostgreSQL — development and production alike — so
# what you build on is what you run on.
#
# The test suite is the one exception, and deliberately so. Django wipes
# the database clean at the start of every test run, so tests must never
# be pointed at real data. They run on an SQLite database held in memory
# instead: nothing is created on the PostgreSQL server, there is no
# second database to look after, and diction_db is never touched.
#
# Which one is used:
#   * running tests: SQLite in memory, always;
#   * DJANGO_DB=postgres or sqlite decides the rest outright;
#   * otherwise PostgreSQL.

# Used only by the test suite, and by DJANGO_DB=sqlite.
SQLITE = {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": BASE_DIR / "db.sqlite3",
    "OPTIONS": {
        # Let a second connection wait rather than fail outright, and
        # keep foreign keys honest.
        "timeout": 20,
        "transaction_mode": "IMMEDIATE",
        "init_command": "PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;",
    },
}

POSTGRES = {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": os.environ.get("POSTGRES_DB", ""),
    "USER": os.environ.get("POSTGRES_USER", ""),
    "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
    "HOST": os.environ.get("POSTGRES_HOST", "127.0.0.1"),
    "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    # Reuse connections between requests, and check one is still alive
    # before handing it to a view.
    "CONN_MAX_AGE": int(os.environ.get("POSTGRES_CONN_MAX_AGE", 60)),
    "CONN_HEALTH_CHECKS": True,
    "OPTIONS": {
        "connect_timeout": 10,
        # "require" when the database is on another host, e.g. a managed
        # provider; "prefer" is right for one on the same machine.
        "sslmode": os.environ.get("POSTGRES_SSLMODE", "prefer"),
    },
}

POSTGRES_READY = all([POSTGRES["NAME"], POSTGRES["USER"], POSTGRES["PASSWORD"]])
DB_CHOICE = os.environ.get("DJANGO_DB", "postgres").strip().lower()
USE_POSTGRES = DB_CHOICE == "postgres" and not TESTING

if USE_POSTGRES and not POSTGRES_READY:
    raise ImproperlyConfigured(
        "PostgreSQL is selected but POSTGRES_DB, POSTGRES_USER and POSTGRES_PASSWORD are not all set. "
        "Fill them in in .env, or set DJANGO_DB=sqlite to work without a database server."
    )

if TESTING:
    # In memory: quick, and gone the moment the run finishes.
    SQLITE = {**SQLITE, "NAME": ":memory:", "TEST": {"NAME": ":memory:"}}

DATABASES = {"default": POSTGRES if USE_POSTGRES else SQLITE}


# ---------------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------

# British English content is core to the product, so the project speaks
# en-gb by default. Nigerian schools run on West Africa Time.
LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Africa/Lagos"
USE_I18N = True
USE_TZ = True


# ---------------------------------------------------------------------------
# Static & media files
# ---------------------------------------------------------------------------

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Render form widgets through the project template setup, so
# templates/admin/widgets/ can show what a file field already holds.
FORM_RENDERER = "django.forms.renderers.TemplatesSetting"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# ---------------------------------------------------------------------------
# Cloudflare R2 — where every uploaded file lives
# ---------------------------------------------------------------------------

R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME", "")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_CONFIGURED = all([R2_ACCOUNT_ID, R2_BUCKET_NAME, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY])

# How long a media link stays valid. The bucket is private, so every link
# the site hands out is signed and expires; long enough for a lesson page
# left open all morning.
# Short enough that a copied address is no use to anyone for long, and long
# enough to play the longest lesson without the link dying mid-way.
R2_LINK_LIFETIME_SECONDS = int(os.environ.get("R2_LINK_LIFETIME_SECONDS", 60 * 60))

R2_STORAGE_OPTIONS = {
    "bucket_name": R2_BUCKET_NAME,
    "endpoint_url": f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
    "access_key": R2_ACCESS_KEY_ID,
    "secret_key": R2_SECRET_ACCESS_KEY,
    "region_name": "auto",
    "signature_version": "s3v4",
    # The bucket already holds files from elsewhere; this site keeps to
    # its own folder so nothing it does can touch those.
    "location": "media",
    # R2 has no ACLs, and a same-named upload must never silently
    # replace a different file — it gets a unique name instead.
    "default_acl": None,
    "file_overwrite": False,
    "querystring_auth": True,
    "querystring_expire": R2_LINK_LIFETIME_SECONDS,
}

# Every FileField and ImageField saves here — admin uploads, student
# recordings and generated pronunciation alike. Without R2 settings the
# site falls back to the local media folder so development still works.
STORAGES = {
    "default": (
        {"BACKEND": "storages.backends.s3.S3Storage", "OPTIONS": R2_STORAGE_OPTIONS}
        if R2_CONFIGURED
        else {"BACKEND": "django.core.files.storage.FileSystemStorage"}
    ),
    # In production the site's own files are served compressed, with a
    # hash in each name, so a browser can cache them forever and still
    # pick up the next release straight away.
    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage.CompressedManifestStaticFilesStorage"
            if PRODUCTION and not TESTING
            # In development: the plain files, with an address that changes
            # whenever a file is saved, so no browser shows a stale stylesheet.
            else "config.static_storage.FreshStaticFilesStorage"
        )
    },
}

WHITENOISE_MAX_AGE = 60 * 60 * 24 * 365


# ---------------------------------------------------------------------------
# Email — password resets and error reports
# ---------------------------------------------------------------------------

if os.environ.get("EMAIL_HOST"):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.environ["EMAIL_HOST"]
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", 587))
    EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = env_flag("EMAIL_USE_TLS", True)
else:
    # Nothing is sent anywhere: messages print in the terminal.
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

DEFAULT_FROM_EMAIL = os.environ.get("DJANGO_FROM_EMAIL", "Diction Masters <no-reply@dictionmasters.com>")
SERVER_EMAIL = DEFAULT_FROM_EMAIL
ADMINS = [("Diction Masters", email) for email in env_list("DJANGO_ADMIN_EMAILS")]


# ---------------------------------------------------------------------------
# Logging — everything to the console, which the server captures
# ---------------------------------------------------------------------------

LOG_LEVEL = os.environ.get("DJANGO_LOG_LEVEL", "INFO" if PRODUCTION else "WARNING").upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
        "mail_admins": {"class": "django.utils.log.AdminEmailHandler", "level": "ERROR"},
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django.request": {
            "handlers": ["console"] + (["mail_admins"] if ADMINS else []),
            "level": "ERROR",
            "propagate": False,
        },
        # The site's own work: look-ups, pronunciations, thumbnails.
        "apps": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

# A custom user model (email login, role, school) — see apps/accounts.
# This must be set before the first migration ever runs.
AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "landing:home"
LOGOUT_REDIRECT_URL = "landing:home"


# ---------------------------------------------------------------------------
# Payments — Paystack
# ---------------------------------------------------------------------------

# Test keys (sk_test_/pk_test_) take pretend payments; swap in live keys to
# take real ones. Prices, plans and the free trial are set in the control
# room, not here. Point Paystack's webhook at /billing/webhook/paystack/.
PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY", "")
PAYSTACK_PUBLIC_KEY = os.environ.get("PAYSTACK_PUBLIC_KEY", "")


# ---------------------------------------------------------------------------
# The Android and iPhone apps (apps/landing/native_app.py, MOBILE_APP_GUIDE.md)
# ---------------------------------------------------------------------------

# Apple and Google Play don't allow selling digital subscriptions inside an
# app through Paystack. In the apps listed here, plans can't be bought: people
# pay on the website and use their plan in the app. "ios,android" is the safe
# setting for the stores; set it to "ios" to allow Paystack in the Android app
# only if Google Play allows it for you (see the guide, section 8).
NATIVE_APP_HIDE_PAYMENTS = env_list("NATIVE_APP_HIDE_PAYMENTS", "ios,android")

# So website links (WhatsApp, email) open straight in the app.
NATIVE_APP_ANDROID_PACKAGE = os.environ.get("NATIVE_APP_ANDROID_PACKAGE", "app.dictionmasters.mobile")
# Google Play Console > your app > Test and release > App integrity > App signing:
# "SHA-256 certificate fingerprint". Several allowed, comma-separated.
NATIVE_APP_ANDROID_SHA256 = env_list("NATIVE_APP_ANDROID_SHA256")
# developer.apple.com > Account > Membership details > Team ID.
NATIVE_APP_IOS_TEAM_ID = os.environ.get("NATIVE_APP_IOS_TEAM_ID", "")
NATIVE_APP_IOS_BUNDLE_ID = os.environ.get("NATIVE_APP_IOS_BUNDLE_ID", NATIVE_APP_ANDROID_PACKAGE)

# The "Get the app" page (/app/get/) and install buttons. Leave any of these
# empty and that option simply isn't offered.
#   The Android app file. Once GitHub publishes it (guide, section 12) use:
#   https://github.com/<owner>/<repo>/releases/latest/download/diction-masters.apk
NATIVE_APP_ANDROID_APK_URL = os.environ.get("NATIVE_APP_ANDROID_APK_URL", "")
#   The app's Google Play and App Store pages, once they're published.
NATIVE_APP_ANDROID_STORE_URL = os.environ.get("NATIVE_APP_ANDROID_STORE_URL", "")
NATIVE_APP_IOS_STORE_URL = os.environ.get("NATIVE_APP_IOS_STORE_URL", "")

# "Update available" in the Android app. The newest version is read from
# GitHub Releases automatically; nothing to set. Optional:
#   NATIVE_APP_ANDROID_MIN_BUILD  apps older than this build number MUST update
#                                 before they carry on (for an important fix).
#   NATIVE_APP_ANDROID_LATEST_BUILD / _LATEST_VERSION / _UPDATE_NOTES
#                                 say the newest version by hand, if the app
#                                 file isn't published on GitHub.
# How long the phone apps stay signed in after the last use (so they open,
# and work offline, without asking for the password again).
NATIVE_APP_SESSION_DAYS = int(os.environ.get("NATIVE_APP_SESSION_DAYS", "180") or 180)
NATIVE_APP_ANDROID_MIN_BUILD = int(os.environ.get("NATIVE_APP_ANDROID_MIN_BUILD", "0") or 0)
NATIVE_APP_ANDROID_LATEST_BUILD = int(os.environ.get("NATIVE_APP_ANDROID_LATEST_BUILD", "0") or 0)
NATIVE_APP_ANDROID_LATEST_VERSION = os.environ.get("NATIVE_APP_ANDROID_LATEST_VERSION", "")
NATIVE_APP_ANDROID_UPDATE_NOTES = os.environ.get("NATIVE_APP_ANDROID_UPDATE_NOTES", "")

# Hosts that lesson pictures and audio are served from (besides this site),
# so the app can keep them for offline study. Cloudflare R2 is included;
# add a custom media domain here if you use one. Each needs a CORS rule
# allowing this site (MOBILE_APP_GUIDE.md, section 11).
OFFLINE_MEDIA_HOSTS = env_list("OFFLINE_MEDIA_HOSTS", "r2.cloudflarestorage.com,r2.dev")


# ---------------------------------------------------------------------------
# Lesson videos, and keeping them for offline viewing (apps/videos)
# ---------------------------------------------------------------------------

# How long a learner may keep a copy before the app checks with the site
# again, and how many of their own devices may hold copies at once.
OFFLINE_VIDEO_LICENSE_DAYS = int(os.environ.get("OFFLINE_VIDEO_LICENSE_DAYS", 7))
MAX_OFFLINE_DEVICES_PER_STUDENT = int(os.environ.get("MAX_OFFLINE_DEVICES_PER_STUDENT", 2))
# A playing link is short-lived; the one that fetches a copy lasts longer,
# because a whole video has to come down over it.
VIDEO_LINK_SECONDS = int(os.environ.get("VIDEO_LINK_SECONDS", 15 * 60))
VIDEO_DOWNLOAD_LINK_SECONDS = int(os.environ.get("VIDEO_DOWNLOAD_LINK_SECONDS", 2 * 60 * 60))

# ---------------------------------------------------------------------------
# OpenAI — hearing a reading, and writing about it
# ---------------------------------------------------------------------------

# One key does all of it: the read-along timings and the live tutor's
# listening (transcription), the tutor's feedback and the Quick Words
# look-up (the chat model). Without a key those features are simply
# switched off, and everything else works as usual.
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
# whisper-1 is the model that gives a time for every word, which is what
# the read-along highlight and the tutor are built on. The newer
# gpt-4o-transcribe models do not return word times.
OPENAI_TRANSCRIBE_MODEL = os.environ.get("OPENAI_TRANSCRIBE_MODEL", "whisper-1")
# For the tutor's feedback and Quick Words. gpt-4o-mini answers in about
# a second; set OPENAI_MODEL to "gpt-4o" for richer writing, more slowly.
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

# Pronunciation audio for newly looked-up words. Without a key and voice
# the words are still saved, just without audio.
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "")
# multilingual_v2 is the most natural voice and the steadiest (~1.5s per
# word). "eleven_flash_v2_5" is quicker but noticeably less natural.
ELEVENLABS_MODEL_ID = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
# The live reading tutor answers in the middle of a reading, so it uses the
# fast model: under a second, where the default takes nearly two.
TUTOR_VOICE_MODEL_ID = os.environ.get("TUTOR_VOICE_MODEL_ID", "eleven_turbo_v2_5")
