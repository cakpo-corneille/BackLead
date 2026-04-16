from datetime import timedelta
import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

# NOTE: environment-specific development overrides are in config/dev.py

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'corsheaders',
    'rest_framework',
    'rest_framework_simplejwt',
    'django_filters',
    # Nécessaire pour la blacklist des refresh tokens après rotation
    'rest_framework_simplejwt.token_blacklist',
    'drf_yasg',
    'accounts',
    'core_data',
    'simulator',
]

MIDDLEWARE = [
    'config.middleware.HybridCORSMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database configuration is provided by environment-specific settings (e.g. config/dev.py)


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'FR-fr'

TIME_ZONE = 'Africa/Porto-Novo'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = 'static/'

# Use custom user model (email as username)
AUTH_USER_MODEL = 'accounts.User'

# JWT Authentication settings
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=24),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    # Activé pour invalider les anciens refresh tokens après rotation,
    # ce qui évite qu'un token volé puisse être réutilisé indéfiniment.
    # Requiert 'rest_framework_simplejwt.token_blacklist' dans INSTALLED_APPS
    # et l'exécution de `python manage.py migrate` pour créer la table.
    'BLACKLIST_AFTER_ROTATION': True,
}

# REST framework : JWT par défaut, routes protégées sauf déclaration explicite contraire
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
}

# Le cache Redis est configuré par les fichiers d'environnement (dev.py / prod.py)
# car l'URL Redis diffère selon l'environnement. On ne le définit pas ici
# pour éviter qu'un Redis inexistant plante l'application au démarrage.

# Media files (for uploaded logos)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# --- BUSINESS LOGIC SETTINGS ---

# OTP Code Validity (seconds)
OTP_TTL = 600       # 10 minutes
DOUBLE_OPT_TTL = 300  # 5 minutes

# Email Deliverability (vérification réelle des domaines MX via DNS)
# Par défaut False pour ne pas bloquer les tests/dev avec des domaines fictifs.
EMAIL_CHECK_DELIVERABILITY = False
