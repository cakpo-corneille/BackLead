from .base import *

"""Paramètres spécifiques à l'environnement de développement.

Ce fichier est importé depuis `config/settings.py` seulement en environnement de dev.
Ne pas mettre d'informations sensibles en production.
"""

APPEND_SLASH = False

# Security
SECRET_KEY = 'django-insecure-l)1j=y)egohs2d=5p=3#phi=ui50$nsd&i*ecne@oq)+wnw-#p'

# Debug
DEBUG = True

# Autoriser l'IP locale et localhost
ALLOWED_HOSTS = ['192.168.43.7', '192.168.43.255', '10.10.10.26', '127.0.0.1', 'localhost', '0.0.0.0']

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

# CORS ouvert en dev comme en prod (cohérent avec l'architecture widget/SDK du projet)
CORS_ALLOW_ALL_ORIGINS = True

# Cache Redis — indispensable ici car le projet utilise `from django.core.cache import cache`.
# Sans cette config, Django tomberait sur son LocMemCache par défaut (mémoire locale,
# non partagée entre processus, perdue au redémarrage), ce qui donnerait un comportement
# différent de la prod et des bugs difficiles à reproduire.
# On utilise la DB Redis n°1 pour bien séparer le cache du broker Celery (DB n°0).
# Redis doit être lancé localement : `redis-server`
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://localhost:6379/1',  # DB 1 = cache (DB 0 = Celery)
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        }
    }
}

# Celery Settings (development)
# DB 0 pour le broker et le backend de résultats Celery
CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

# Static files (development)
STATIC_ROOT = BASE_DIR / 'staticfiles'
