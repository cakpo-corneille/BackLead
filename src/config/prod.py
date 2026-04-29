
from .base import *
from decouple import config, Csv
import dj_database_url
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

"""
Production Overrides

This file configures the application for a production environment. It uses python-decouple
to load settings from environment variables or a .env file, ensuring that no sensitive
information is hardcoded. 
"""

# -- CORE DJANGO SECURITY --
SECRET_KEY = config('SECRET_KEY', default=None)
if not SECRET_KEY:
    raise RuntimeError('SECRET_KEY must be set in the environment for production.')

DEBUG = False

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='', cast=Csv())


# -- ERROR TRACKING (Sentry) --
SENTRY_DSN = config('SENTRY_DSN', default=None)
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        traces_sample_rate=0.1,
        environment=config('ENVIRONMENT', default='production'),
    )


# -- STATIC FILES & MIDDLEWARE (Whitenoise) --
MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
STATIC_ROOT = BASE_DIR / 'staticfiles'


# -- MEDIA STORAGE (S3-compatible via Railway Bucket) --
# This block checks for Railway's bucket environment variables.
# If they exist, it configures django-storages to use the S3-compatible bucket.
# Otherwise, it falls back to the local media storage settings from base.py.
if config('BUCKET', default=None):
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }

    AWS_ACCESS_KEY_ID = config('ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = config('SECRET_ACCESS_KEY')
    AWS_STORAGE_BUCKET_NAME = config('BUCKET')
    AWS_S3_REGION_NAME = config('REGION')
    AWS_S3_ENDPOINT_URL = f"https://{config('ENDPOINT')}"
    AWS_S3_ADDRESSING_STYLE = 'path'
    AWS_S3_FILE_OVERWRITE = False
    AWS_QUERYSTRING_AUTH = True
    AWS_QUERYSTRING_EXPIRE = 3600
    AWS_LOCATION = 'media'

    MEDIA_URL = f"https://{config('ENDPOINT')}/{config('BUCKET')}/media/"


# -- DATABASE --
DATABASES = {
    'default': dj_database_url.config(default=config('DATABASE_URL'))
}


# -- SECURITY HEADERS & COOKIES --
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=True, cast=bool)
SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=31536000, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')


# -- CORS (Cross-Origin Resource Sharing) --
# Stratégie Hybride:
# 1. Pour les API privées (dashboard), on utilise une liste blanche stricte.
# 2. Pour les API publiques (widget/portail), on autorise toutes les origines.

# La liste des domaines de confiance pour accéder aux API privées (votre dashboard).
CORS_ALLOWED_ORIGINS = config('CORS_ALLOWED_ORIGINS', default='', cast=Csv())

# Autorise l'envoi de cookies (et donc de tokens JWT) depuis ces domaines.
CORS_ALLOW_CREDENTIALS = True

# Par défaut, on n'autorise PAS toutes les origines.
CORS_ALLOW_ALL_ORIGINS = False


# -- EMAIL CONFIGURATION (Flexible & Agnostic) --
EMAIL_PROVIDER = config('EMAIL_PROVIDER', default='console').lower()
EMAIL_API_KEY = config('EMAIL_API_KEY', default=None)
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='WiFi Marketing <no-reply@example.com>')

EMAIL_PROVIDER_MAP = {
    'brevo': {
        'backend': 'anymail.backends.brevo.EmailBackend',
        'key_name': 'BREVO_API_KEY' 
    },
    'sendgrid': {
        'backend': 'anymail.backends.sendgrid.EmailBackend',
        'key_name': 'SENDGRID_API_KEY'
    },
    'mailgun': {
        'backend': 'anymail.backends.mailgun.EmailBackend',
        'key_name': 'MAILGUN_API_KEY'
    },
    'smtp': {
        'backend': 'django.core.mail.backends.smtp.EmailBackend',
        'key_name': None
    },
    'console': {
        'backend': 'django.core.mail.backends.console.EmailBackend',
        'key_name': None
    }
}

provider_config = EMAIL_PROVIDER_MAP.get(EMAIL_PROVIDER, EMAIL_PROVIDER_MAP['console'])

EMAIL_BACKEND = provider_config['backend']
ANYMAIL = {}

if provider_config['key_name'] and EMAIL_API_KEY:
    ANYMAIL[provider_config['key_name']] = EMAIL_API_KEY

if EMAIL_PROVIDER == 'smtp':
    EMAIL_HOST = config('EMAIL_HOST', default='localhost')
    EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
    EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
    EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
    EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')


# -- SMS CONFIGURATION (Flexible & Agnostic) --
SMS_PROVIDER = config('SMS_PROVIDER', default='console').lower()

SMS_GATEWAYS = {
    'brevo': {
        'API_KEY': config('BREVO_SMS_API_KEY', default=None),
        'SENDER_ID': config('BREVO_SMS_SENDER_ID', default=None),
        'URL': config('BREVO_SMS_API_URL', default='https://api.brevo.com/v3/transactionalSMS/sms'),
    },
    'fastermessage': {
        'API_KEY': config('FASTERMESSAGE_API_KEY', default=None),
        'SENDER_ID': config('FASTERMESSAGE_SENDER_ID', default=None),
        'URL': config('FASTERMESSAGE_API_URL', default='https://api.fastermessage.com/v1/send'),
    },
    'hub2': {
        'TOKEN': config('HUB2_TOKEN', default=None),
        'SENDER_ID': config('HUB2_SENDER_ID', default=None),
        'URL': config('HUB2_API_URL', default='https://api.hub2.com/sms/send'),
    },
    'console': {}
}

ACTIVE_SMS_CONFIG = SMS_GATEWAYS.get(SMS_PROVIDER, SMS_GATEWAYS['console'])


# -- BUSINESS LOGIC --
EMAIL_CHECK_DELIVERABILITY = config('EMAIL_CHECK_DELIVERABILITY', default=True, cast=bool)


# -- CELERY & CACHE (Redis) --
CELERY_BROKER_URL = config('CELERY_BROKER_URL')
CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default=CELERY_BROKER_URL)
CELERY_TASK_ALWAYS_EAGER = config('CELERY_TASK_ALWAYS_EAGER', default=True)


REDIS_URL = config('REDIS_URL', default='redis://localhost:6379/1')
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    }
}


# -- LOGGING --
LOG_LEVEL = config('LOG_LEVEL', default='INFO').upper()
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file_error': {
            'level': 'ERROR',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'django_error.log',
            'maxBytes': 1024 * 1024 * 5,  # 5 MB
            'backupCount': 2,
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console', 'file_error'],
        'level': LOG_LEVEL,
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file_error'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
    },
}
