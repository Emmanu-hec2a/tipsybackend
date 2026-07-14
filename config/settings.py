# settings.py - Django Settings Configuration

import os
from pathlib import Path
import dj_database_url
from dotenv import load_dotenv

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
DEBUG = os.environ.get('DEBUG', 'True') == 'True'

SITE_URL = os.environ.get('SITE_URL', 'https://tipsytheoryy.com')

ALLOWED_HOSTS = ['*']

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

# SECURE_SSL_REDIRECT = True
# SESSION_COOKIE_SECURE = True
# CSRF_COOKIE_SECURE = True


# settings.py
SITE_ID = 1

# Application definition
INSTALLED_APPS = [
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
    'urbanfoods',  # Your app name
    'rest_framework',  # For API endpoints
    'corsheaders',
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

# Database Configuration
# Use PostgreSQL from Railway if DATABASE_URL exists, otherwise SQLite for local dev
if os.environ.get('DATABASE_URL'):
    DATABASES = {
        'default': dj_database_url.config(
            default=os.environ.get('DATABASE_URL'),
            conn_max_age=600,
            conn_health_checks=True,
            ssl_require=True,
        )
    }
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

# Use Cloudflare R2 for media files in production
if not DEBUG and os.environ.get('R2_ACCESS_KEY_ID'):
    DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
    # If using a public bucket URL (e.g. pub-xxxxx.r2.dev) or a custom domain
    if AWS_S3_CUSTOM_DOMAIN:
        MEDIA_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/"
    else:
        # Fallback to a default format if you have one, or keep /media/ 
        # but django-storages will return the full S3 URL in most cases
        pass

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
# Static files storage with WhiteNoise
if not DEBUG:
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
else:
    STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.ManifestStaticFilesStorage'

# Session Configuration
SESSION_COOKIE_AGE = 604800  # 1 week
SESSION_SAVE_EVERY_REQUEST = True
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
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.ScopedRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'merchant_blast': '3/minute',
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

# Logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}


LOGIN_URL = 'login'

# CORS Configuration
CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://tipsytheoryy-merchant.pages.dev",
    "https://api.tipsytheoryy.com",
    "https://merchants.tipsytheoryy.com",
]

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
