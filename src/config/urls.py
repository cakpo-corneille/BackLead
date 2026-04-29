from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
import os
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # Sécurité : On peut changer 'admin/' par une valeur secrète via env
    path(os.environ.get('DJANGO_ADMIN_URL', 'admin/'), admin.site.urls),

    # API v1 - Logique métier
    path('api/', include('api.urls')),

    # Authentification JWT
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]


# Les URLs suivantes sont UNIQUEMENT ajoutées en mode DEBUG
if settings.DEBUG:
    # Pour servir les fichiers médias (uploads utilisateurs) pendant le développement
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    
