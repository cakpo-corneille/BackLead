from .base import *

"""Paramètres spécifiques à l'environnement de développement.

Ce fichier est importé depuis `config/settings.py` seulement en environnement de dev.
Ne pas mettre d'informations sensibles en production.
"""



# Security
SECRET_KEY = 'django-insecure-l)1j=y)egohs2d=5p=3#phi=ui50$nsd&i*ecne@oq)+wnw-#p'

# Debug
DEBUG = True

# Autoriser l'IP locale et localhost
ALLOWED_HOSTS = ['*']

# Database (développement local)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Email settings for development
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = 'no-reply@localhost'

# Frontend URL (used to build verification links)
FRONTEND_URL = 'http://localhost:9002'

WIDGET_SCRIPT_URL = 'http://localhost:8000/static/core_data/widget.js'



# Cache en mémoire locale (pas Redis) pour le dev Replit
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}

# Celery Settings (development) — mode synchrone, sans Redis
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

# Static files (development)
STATIC_ROOT = BASE_DIR / 'staticfiles'

# SMS Configuration (Default to console in dev)
ACTIVE_SMS_CONFIG = {}

# Désactiver la vérification réelle des domaines email en dev
EMAIL_CHECK_DELIVERABILITY = False
