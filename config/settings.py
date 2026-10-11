"""
Cấu hình LAM Coffee System.

Mọi giá trị khác nhau giữa máy chạy thử và máy chủ thật đọc từ biến môi trường
(hoặc tệp .env ở thư mục gốc). Xem .env.example.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path):
    """Nạp tệp .env đơn giản (KEY=VALUE) mà không cần thư viện ngoài."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(BASE_DIR / ".env")


def env(key, default=None):
    return os.environ.get(key, default)


def env_bool(key, default=False):
    return env(key, str(default)).lower() in ("1", "true", "yes", "on")


def env_list(key, default=""):
    return [item.strip() for item in env(key, default).split(",") if item.strip()]


# --- Bảo mật cơ bản -----------------------------------------------------------

DEBUG = env_bool("DJANGO_DEBUG", True)

SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError("Thiếu DJANGO_SECRET_KEY khi DJANGO_DEBUG=false.")
    SECRET_KEY = "django-insecure-chi-dung-khi-chay-thu-tren-may-ca-nhan"

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")


# --- Ứng dụng -----------------------------------------------------------------

INSTALLED_APPS = [
    "apps.core.apps.OwnerAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # Ứng dụng của LAM Coffee
    "apps.core",
    "apps.audit",
    "apps.accounts",
    "apps.staff",
    "apps.catalog",
    "apps.inventory",
    "apps.shifts",
    "apps.orders",
    "apps.control",
    "apps.reports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.accounts.permissions.DeniedAccessLogMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.site",
                "apps.core.context_processors.navigation",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# --- Cơ sở dữ liệu --------------------------------------------------------------
# Mặc định SQLite để chạy thử; đặt DB_ENGINE=postgresql khi triển khai thật
# (cần cài thêm psycopg). Mã nguồn không đổi giữa hai loại.

if env("DB_ENGINE", "sqlite") == "postgresql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("DB_NAME", "lamcoffee"),
            "USER": env("DB_USER", "lamcoffee"),
            "PASSWORD": env("DB_PASSWORD", ""),
            "HOST": env("DB_HOST", "localhost"),
            "PORT": env("DB_PORT", "5432"),
            "ATOMIC_REQUESTS": True,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / env("SQLITE_NAME", "db.sqlite3"),
            "ATOMIC_REQUESTS": True,
            # Mỗi giao dịch giữ khóa ghi ngay từ đầu, nên hai đơn đồng thời được xử lý lần lượt.
            "OPTIONS": {"transaction_mode": "IMMEDIATE", "timeout": 20},
            # Kiểm thử dùng tệp thật để thử được nhiều luồng ghi đồng thời.
            "TEST": {"NAME": str(BASE_DIR / "test_db.sqlite3")},
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --- Tài khoản và phiên đăng nhập (NFR-06) --------------------------------------

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Thời hạn mỗi cấp duyệt yêu cầu điều chỉnh trước khi chuyển cấp (BRU-09, AC-24).
APPROVAL_LEVEL_MINUTES = int(env("APPROVAL_LEVEL_MINUTES", 3))

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:home"
LOGOUT_REDIRECT_URL = "accounts:login"

AUTHENTICATION_BACKENDS = ["apps.accounts.backends.LockAwareBackend"]

# Tạm khóa tài khoản sau nhiều lần sai mật khẩu liên tiếp.
LOGIN_MAX_FAILED_ATTEMPTS = int(env("LOGIN_MAX_FAILED_ATTEMPTS", 5))
LOGIN_LOCK_MINUTES = int(env("LOGIN_LOCK_MINUTES", 15))

# Tự đăng xuất sau 15 phút không thao tác (gia hạn mỗi lần có yêu cầu).
SESSION_COOKIE_AGE = int(env("SESSION_IDLE_SECONDS", 15 * 60))
SESSION_SAVE_EVERY_REQUEST = True


# --- Bản địa hóa (NFR-12) ---------------------------------------------------------

LANGUAGE_CODE = "vi"
LANGUAGES = [("vi", "Tiếng Việt")]
TIME_ZONE = "Asia/Ho_Chi_Minh"
USE_I18N = True
USE_TZ = True
USE_THOUSAND_SEPARATOR = True
THOUSAND_SEPARATOR = "."
DECIMAL_SEPARATOR = ","
NUMBER_GROUPING = 3


# --- Tệp tĩnh ---------------------------------------------------------------------

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Ảnh chứng từ chi tiền (BRU-33).
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / env("MEDIA_DIR", "media")
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024


# --- Thông tin cửa hàng (NFR-18: dữ liệu chính có mã cửa hàng) -------------------

LAM_STORE_CODE = env("LAM_STORE_CODE", "LAM01")
LAM_STORE_NAME = env("LAM_STORE_NAME", "LAM Coffee")


# --- Triển khai thật ----------------------------------------------------------------

if not DEBUG:
    # Tên tệp tĩnh có mã băm để điện thoại luôn tải bản mới sau mỗi lần cập nhật.
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"},
    }
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}

# Kiểm thử chạy nhanh hơn với bộ băm mật khẩu đơn giản (chỉ khi chạy manage.py test).
import sys  # noqa: E402

if len(sys.argv) > 1 and sys.argv[1] == "test":
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
