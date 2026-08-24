# settings.py - Django Settings Configuration

import os
from pathlib import Path
import dj_database_url
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

# Load environment variables from .env file
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('SECRET_KEY')

# settings.py
SESSION_ENGINE = "django.contrib.sessions.backends.db"  # default
SESSION_COOKIE_NAME = "sessionid"  # default for users

# Extra config for admin
ADMIN_SESSION_ENGINE = "django.contrib.sessions.backends.db"
ADMIN_SESSION_COOKIE_NAME = "admin_sessionid"

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')


# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DEBUG', 'False').lower() in ('1', 'true', 'yes')

SITE_URL = os.environ.get('SITE_URL', 'https://api.tipsytheoryy.com')

ALLOWED_HOSTS = [host.strip() for host in os.environ.get(
    'ALLOWED_HOSTS',
    'localhost,127.0.0.1,api.tipsytheoryy.com,tipsybackend.up.railway.app',
).split(',') if host.strip()]

if not SECRET_KEY:
    raise ImproperlyConfigured('SECRET_KEY must be set.')
if not DEBUG and '*' in ALLOWED_HOSTS:
    raise ImproperlyConfigured('Wildcard ALLOWED_HOSTS is forbidden in production.')

CSRF_TRUSTED_ORIGINS = [
    "http://127.0.0.1:5050",
    "http://localhost:8000",
    "http://192.168.0.11:8000",
    "https://tipsytheoryy.com",
    "https://www.tipsytheoryy.com",
    "https://*.railway.app",
    "https://tipsybackend.up.railway.app",
    "https://tipsytheoryy-merchant.pages.dev",
    "https://api.tipsytheoryy.com",
    "https://merchants.tipsytheoryy.com",
]

from corsheaders.defaults import default_headers
CORS_ALLOW_HEADERS = list(default_headers) + [
    "x-store-id",
]

# SECURE_SSL_REDIRECT = True
# SESSION_COOKIE_SECURE = True
# CSRF_COOKIE_SECURE = True


# settings.py
SITE_ID = 1

# Application definition
INSTALLED_APPS = [
    'daphne',
    'unfold',
    'unfold.contrib.filters',
    'django.contrib.admin',  # Django's built-in admin
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'storages',
    'django.contrib.sites',  # Required for sitemaps
    'django.contrib.sitemaps',
    'django_celery_beat',
    'channels',
    'urbanfoods',  # Your app name
    'rest_framework',  # For API endpoints
    'corsheaders',
    'anymail',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'urbanfoods.middleware.CustomAdminSessionMiddleware',
    'urbanfoods.middleware.StoreMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'urbanfoods.audit_logging.AdminActionMiddleware',  # 🛡️ Capture IP for admin audit logs
    'urbanfoods.middleware.RateLimitHeadersMiddleware',  # 🛡️ Add rate limit response headers (Day 2)
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django.middleware.gzip.GZipMiddleware', # Compress responses for faster load times
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'urbanfoods.context_processors.store_type',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            "hosts": [os.environ.get('REDIS_URL', 'redis://localhost:6379/0')],
        },
    },
}

# Database Configuration
# Use PostgreSQL from Railway if DATABASE_URL exists, otherwise SQLite for local dev
if os.environ.get('DATABASE_URL'):
    try:
        DB_CONN_MAX_AGE = max(0, int(os.environ.get('DB_CONN_MAX_AGE', '60')))
        DB_CONNECT_TIMEOUT = max(1, int(os.environ.get('DB_CONNECT_TIMEOUT', '5')))
    except ValueError:
        DB_CONN_MAX_AGE = 60
        DB_CONNECT_TIMEOUT = 5
    DATABASES = {
        'default': dj_database_url.config(
            default=os.environ.get('DATABASE_URL'),
            conn_max_age=DB_CONN_MAX_AGE,
            conn_health_checks=True,
            ssl_require=True,
        )
    }
    DATABASES['default'].setdefault('OPTIONS', {})['connect_timeout'] = DB_CONNECT_TIMEOUT
else:
    # Local development fallback
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# Custom User Model
AUTH_USER_MODEL = 'urbanfoods.User'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {
            'min_length': 6,
        }
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Nairobi'  # Kenya timezone
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

# Media files (User uploads)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Cloudflare R2 Configuration
AWS_ACCESS_KEY_ID = os.environ.get('R2_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.environ.get('R2_SECRET_ACCESS_KEY')
AWS_STORAGE_BUCKET_NAME = os.environ.get('R2_BUCKET_NAME')
AWS_S3_ENDPOINT_URL = f"https://{os.environ.get('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com"
AWS_S3_CUSTOM_DOMAIN = os.environ.get('R2_CUSTOM_DOMAIN') # e.g. media.tipsytheoryy.com
AWS_S3_REGION_NAME = 'auto'
AWS_S3_FILE_OVERWRITE = False
AWS_DEFAULT_ACL = None

# 🛡️ PCI DSS: AWS Secrets Manager Configuration for Payment Credentials
# Enable AWS Secrets Manager for storing M-Pesa credentials
# Set USE_AWS_SECRETS_MANAGER=true and provide AWS credentials to enable
USE_AWS_SECRETS_MANAGER = os.environ.get('USE_AWS_SECRETS_MANAGER', 'false').lower() in ('1', 'true', 'yes')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
AWS_KMS_KEY_ID = os.environ.get('AWS_KMS_KEY_ID', 'alias/tipsy-payment-keys')
AWS_ROTATION_LAMBDA_ARN = os.environ.get('AWS_ROTATION_LAMBDA_ARN')  # Optional: for automatic credential rotation

# AWS Secrets Manager requires separate credentials (for Secrets Manager, not R2)
# Set AWS_SM_ACCESS_KEY_ID and AWS_SM_SECRET_ACCESS_KEY in environment
# This allows separation of concerns between storage and secrets management
AWS_SM_ACCESS_KEY_ID = os.environ.get('AWS_SM_ACCESS_KEY_ID', AWS_ACCESS_KEY_ID)  # Fallback to R2 creds
AWS_SM_SECRET_ACCESS_KEY = os.environ.get('AWS_SM_SECRET_ACCESS_KEY', AWS_SECRET_ACCESS_KEY)

# Use Cloudflare R2 for media files in production
# Check for R2_ACCESS_KEY_ID to ensure we have credentials
if os.environ.get('R2_ACCESS_KEY_ID'):
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage" if not DEBUG else "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
    
    # If using a public bucket URL (e.g. pub-xxxxx.r2.dev) or a custom domain
    if AWS_S3_CUSTOM_DOMAIN:
        MEDIA_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/"
    else:
        # Fallback: construct the public R2 URL if bucket name and account ID are present
        if AWS_STORAGE_BUCKET_NAME and os.environ.get('R2_ACCOUNT_ID'):
            MEDIA_URL = f"https://{AWS_STORAGE_BUCKET_NAME}.{os.environ.get('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com/"
else:
    # Local storage fallback
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage" if not DEBUG else "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }

# 🛡️ PCI DSS: Database Encryption at Rest (Day 4 - Req 3.4)
# Encrypt sensitive columns in database (phone_number, email, etc.)
# Generate key with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key())"
ENCRYPTION_MASTER_KEY = os.environ.get(
    'ENCRYPTION_MASTER_KEY',
    'INSECURE_KEY_CHANGE_IN_PRODUCTION'  # ← Must be set in environment!
)

# Old keys for key rotation support
# If rotating to new key, keep old key here for decryption of existing data
ENCRYPTION_MASTER_KEY_OLD = os.environ.get('ENCRYPTION_MASTER_KEY_OLD', '')
if ENCRYPTION_MASTER_KEY_OLD:
    ENCRYPTION_MASTER_KEY_OLD = [ENCRYPTION_MASTER_KEY_OLD]

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# 🛡️ Session Configuration (PCI DSS - Req A2:2021)
# Secure session cookies against XSS, CSRF, and session hijacking
SESSION_COOKIE_AGE = 3600  # 1 hour (was 1 week) - PCI DSS: Short session lifetime
SESSION_COOKIE_HTTPONLY = True  # 🛡️ Prevent XSS JavaScript access to session cookie
SESSION_COOKIE_SECURE = True  # 🛡️ Only send over HTTPS (prevents network eavesdropping)
SESSION_COOKIE_SAMESITE = 'Lax'  # 🛡️ CSRF protection: cookies only sent in same-site contexts
SESSION_SAVE_EVERY_REQUEST = True  # Refresh session timeout on each request
CSRF_COOKIE_SECURE = True  # 🛡️ CSRF cookie only over HTTPS
CSRF_COOKIE_HTTPONLY = False  # ⚠️ Must be False for CSRF to work (but Lax SameSite protects)
SESSION_EXPIRE_AT_BROWSER_CLOSE = True  # 🛡️ Clear session when browser closes (short-lived)
PASSWORD_RESET_TIMEOUT = 1800  # 30 minutes

# Email Configuration (for password reset)  Development
#EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'  
# For production:
# Force Django to use certifi's CA bundle
EMAIL_BACKEND = "sgbackend.SendGridBackend"
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL")
SENDGRID_SANDBOX_MODE_IN_DEBUG = False
SENDGRID_ECHO_TO_STDOUT = True
ADMIN_NOTIFICATION_EMAIL = os.environ.get('ADMIN_NOTIFICATION_EMAIL')
IS_RAILWAY = os.environ.get("RAILWAY_ENVIRONMENT") is not None

# Telegram Bot config
TELEGRAM_BOTT_TOKEN=os.environ.get('TELEGRAM_BOTT_TOKEN')
TELEGRAM_CHATT_ID=os.environ.get('TELEGRAM_CHATT_ID')
TELEGRAM_CHATT_IDS=os.environ.get('TELEGRAM_CHATT_IDS')

# Enhanced Bot Config
TELEGRAM_ADMIN_BOT_TOKEN = os.environ.get('TELEGRAM_ADMIN_BOT_TOKEN')
TELEGRAM_MERCHANT_BOT_TOKEN = os.environ.get('TELEGRAM_MERCHANT_BOT_TOKEN')
TELEGRAM_ADMIN_CHAT_ID = os.environ.get('TELEGRAM_ADMIN_CHAT_ID')


from datetime import timedelta

# REST Framework Configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_VERSIONING_CLASS': 'rest_framework.versioning.URLPathVersioning',
    'ALLOWED_VERSIONS': ['v1'],
    'DEFAULT_VERSION': 'v1',
    # 🛡️ Rate Limiting (Day 2: OWASP A1:2021 - Broken Access Control)
    'DEFAULT_THROTTLE_CLASSES': [
        'urbanfoods.rate_limiting.PaymentStatusThrottle',      # 30/hour per user
        'urbanfoods.rate_limiting.GlobalAuthenticatedThrottle', # 1000/hour per user
        'urbanfoods.rate_limiting.GlobalAnonymousThrottle',    # 100/hour per IP
        'urbanfoods.rate_limiting.GlobalIPThrottle',           # 10000/hour per IP
        'urbanfoods.rate_limiting.ListEndpointThrottle',       # 30/hour (auth), 10/hour (anon)
    ],
    'DEFAULT_THROTTLE_RATES': {
        # Legacy rates (kept for backward compatibility, overridden by Redis throttles)
        'merchant_blast': '3/minute',
        'payment_initiation': '5/minute',
        'shiriki_session': '30/minute',
        'payment_status': '30/hour',          # Updated: was 60/minute
        'payment_status_per_payment': '12/minute',
        'payment_query': '10/minute',
        'auth_login': '10/minute',
    },
}

# Celery Configuration
REDIS_URL = os.environ.get('REDIS_URL')
CELERY_BROKER_URL = REDIS_URL if REDIS_URL else 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = REDIS_URL if REDIS_URL else 'redis://localhost:6379/0'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_TRACK_STARTED = True
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_RESULT_EXPIRES = 3600
CELERY_TASK_SOFT_TIME_LIMIT = 240
CELERY_TASK_TIME_LIMIT = 300
try:
    CELERY_WORKER_CONCURRENCY = max(1, int(os.environ.get('CELERY_WORKER_CONCURRENCY', '4')))
    CELERY_WORKER_MAX_TASKS_PER_CHILD = max(1, int(os.environ.get('CELERY_WORKER_MAX_TASKS_PER_CHILD', '500')))
except ValueError:
    CELERY_WORKER_CONCURRENCY = 4
    CELERY_WORKER_MAX_TASKS_PER_CHILD = 500
CELERY_BROKER_TRANSPORT_OPTIONS = {
    'visibility_timeout': int(os.environ.get('CELERY_VISIBILITY_TIMEOUT', '900')),
}
CELERY_TASK_ROUTES = {
    'urbanfoods.tasks.initiate_payment_attempt_task': {'queue': 'payment_initiation'},
    'urbanfoods.tasks.requeue_deferred_payment_attempts': {'queue': 'payment_initiation'},
    'urbanfoods.tasks.trigger_stk_push_task': {'queue': 'payment_initiation'},
    'urbanfoods.tasks.reconcile_payment_attempt_task': {'queue': 'payment_reconciliation'},
    'urbanfoods.tasks.review_stale_initiating_payment_attempts': {'queue': 'payment_reconciliation'},
    'urbanfoods.tasks.reconcile_pending_mpesa_payments': {'queue': 'payment_reconciliation'},
    'urbanfoods.tasks.reconcile_pending_billing_payments': {'queue': 'payment_reconciliation'},
    'urbanfoods.tasks.process_outbox_event': {'queue': 'payment_notifications'},
    'urbanfoods.tasks.send_lifecycle_notification_task': {'queue': 'payment_notifications'},
    'urbanfoods.tasks.post_payment_confirmation_task': {'queue': 'payment_notifications'},
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(days=7),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=30),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
}

# Caching (Redis recommended for production)
if os.environ.get('REDIS_URL'):
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': os.environ.get('REDIS_URL'),
            'OPTIONS': {
                'socket_connect_timeout': 2,
                'socket_timeout': 2,
                'retry_on_timeout': True,
            },
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'unique-snowflake',
        }
    }

# Security Settings (Production)
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True # Enable XSS protection in browsers
    SECURE_CONTENT_TYPE_NOSNIFF = True # Prevent MIME type sniffing
    SECURE_HSTS_SECONDS = 31536000 
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True # Enforce HSTS on all subdomains
    SECURE_HSTS_PRELOAD = True # Allow site to be included in browser preload lists
    X_FRAME_OPTIONS = 'DENY' # Prevent clickjacking
    SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin" # Control referrer information sent with requests
    
    # Trust Railway's proxy headers
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https') 

# 🛡️ Logging Configuration with PII Masking (PCI DSS - Req 3.4)
# All payment-related logs are automatically masked to prevent data leaks
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "pii_masking": {
            "()": "urbanfoods.logging_filters.PIIMaskingFilter",
        },
    },
    "formatters": {
        "verbose": {
            "format": "[{levelname}] {asctime} {name} {funcName}:{lineno} - {message}",
            "style": "{",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
            "filters": ["pii_masking"],  # 🛡️ Apply PII masking to all console logs
        },
        "payment_handler": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
            "filters": ["pii_masking"],  # 🛡️ Mask all payment logs
        },
    },
    "loggers": {
        "urbanfoods.mpesa_utils": {
            "handlers": ["payment_handler"],
            "level": "INFO",
            "propagate": False,
        },
        "urbanfoods.payment_initiation": {
            "handlers": ["payment_handler"],
            "level": "INFO",
            "propagate": False,
        },
        "urbanfoods.payment_service": {
            "handlers": ["payment_handler"],
            "level": "INFO",
            "propagate": False,
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}


LOGIN_URL = 'login'

# 🛡️ CORS Configuration (OWASP A7:2021 - Cross-Origin Resource Sharing)
# Only allow requests from explicitly whitelisted origins (HTTPS only in production)
CORS_ALLOWED_ORIGINS = [
    # Development (local only, removed from production)
    "http://localhost:5173" if DEBUG else None,
    "http://127.0.0.1:5173" if DEBUG else None,
    # Production domains (HTTPS only)
    "https://app.tipsytheoryy.com",          # Flutter app
    "https://merchant.tipsytheoryy.com",     # Merchant web portal
    "https://merchants.tipsytheoryy.com",    # Alternative merchant domain
    "https://admin.tipsytheoryy.com",        # Admin dashboard
    "https://api.tipsytheoryy.com",          # API domain
    "https://tipsytheoryy-merchant.pages.dev", # Netlify preview
]
# Remove None entries (development URLs when not in DEBUG)
CORS_ALLOWED_ORIGINS = [origin for origin in CORS_ALLOWED_ORIGINS if origin is not None]

# ⚠️ SECURITY NOTES:
# NEVER use wildcards (*) or broad patterns like *.com
# NEVER allow http:// in production (HTTPS only)
# NEVER trust the Origin header blindly

from corsheaders.defaults import default_headers
CORS_ALLOW_HEADERS = list(default_headers) + [
    "x-store-id",
]

CORS_ALLOW_CREDENTIALS = True  # Allow cookies/auth headers with CORS requests
CORS_MAX_AGE = 600  # Cache preflight for 10 minutes to reduce requests
CORS_EXPOSE_HEADERS = ["Content-Type", "X-CSRFToken"]  # Headers accessible to frontend JS

# MPESA Configuration
MPESA_CONSUMER_KEY = os.environ.get('MPESA_CONSUMER_KEY')
MPESA_CONSUMER_SECRET = os.environ.get('MPESA_CONSUMER_SECRET')
MPESA_SHORTCODE = os.environ.get('MPESA_SHORTCODE')  # Default sandbox shortcode
MPESA_PASSKEY = os.environ.get('MPESA_PASSKEY')
MPESA_PAYBILL_NUMBER = os.environ.get('MPESA_PAYBILL_NUMBER')
MPESA_TILL_NUMBER = os.environ.get('MPESA_TILL_NUMBER')
ACCOUNT_NUMBER = os.environ.get('ACCOUNT_NUMBER')
MPESA_CALLBACK_URL = os.environ.get('MPESA_CALLBACK_URL')
# Payment Credentials (Managed via PlatformConfig and Store models)
MPESA_PRODUCTION = os.environ.get('MPESA_PRODUCTION', 'False')
ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY')
TRUSTED_PROXY_IPS = {
    value.strip() for value in os.environ.get('TRUSTED_PROXY_IPS', '').split(',') if value.strip()
}

# Anymail & Resend Configuration
ANYMAIL = {
    "RESEND_API_KEY": os.environ.get("RESEND_API_KEY"),
}
EMAIL_BACKEND = "anymail.backends.resend.EmailBackend"
DEFAULT_FROM_EMAIL = "Tipsy Theoryy <support@s.tipsytheoryy.com>"
SERVER_EMAIL = "support@s.tipsytheoryy.com"
